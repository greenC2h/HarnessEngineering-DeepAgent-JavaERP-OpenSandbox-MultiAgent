"""仅使用 mock 覆盖预热保留实例归属、访问续期和关闭竞态。"""

from __future__ import annotations

import asyncio
import itertools
import threading
import unittest
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from opensandbox.exceptions import SandboxApiException

from agent.backends.sandbox_manager import SandboxManager
from agent.config import OPEN_SANDBOX_SANDBOX_TIMEOUT_SECONDS, SKILLS_ROOT


MODULE = "agent.backends.sandbox_manager"


class SandboxConfigurationTests(unittest.IsolatedAsyncioTestCase):
    """验证缺失外部沙箱凭据时的服务可用性边界。"""

    async def test_missing_api_key_defers_failure_until_a_sandbox_is_requested(self) -> None:
        """开发服务可启动，但实际 Agent 执行必须明确拒绝无凭据的沙箱请求。"""
        with patch(f"{MODULE}.OPEN_SANDBOX_API_KEY", None):
            manager = SandboxManager(MagicMock())
            await manager.initialize()
            self.assertIsNone(manager._warm_task)
            with self.assertRaisesRegex(RuntimeError, "OPEN_SANDBOX_API_KEY"):
                await manager.get_backend("user")
            await manager.close()


class SandboxPrewarmTests(unittest.IsolatedAsyncioTestCase):
    """任务启动前替换所有 SDK、存储和数据植入边界。"""

    async def asyncSetUp(self) -> None:
        self.enterContext(patch(f"{MODULE}.OPEN_SANDBOX_API_KEY", "test"))
        self.enterContext(patch(f"{MODULE}.OPEN_SANDBOX_PREWARM_ENABLED", True))
        self.admin = MagicMock()
        self.admin.get_sandbox_info.return_value = SimpleNamespace(
            status=SimpleNamespace(state="Running"),
        )
        self.enterContext(patch(f"{MODULE}.SandboxManagerSync.create", return_value=self.admin))
        self.instances: dict[str, MagicMock] = {}
        identifiers = itertools.count()

        def create(**kwargs):
            sandbox = MagicMock(id=f"sandbox-{next(identifiers)}")
            sandbox.is_healthy.return_value = True
            self.instances[sandbox.id] = sandbox
            return sandbox

        self.create = self.enterContext(patch(f"{MODULE}.SandboxSync.create", side_effect=create))
        self.connect = self.enterContext(patch(
            f"{MODULE}.SandboxSync.connect", side_effect=lambda identifier, **kwargs: self.instances[identifier],
        ))
        self.synchronizer = self.enterContext(patch(f"{MODULE}.SandboxSkillSynchronizer"))
        self.records: dict[str, dict[str, str]] = {}

        async def read(namespace, key):
            value = self.records.get(namespace[-1])
            return SimpleNamespace(value=value.copy()) if value is not None else None

        async def write(namespace, key, value, **kwargs):
            self.records[namespace[-1]] = value.copy()

        self.store = SimpleNamespace(aget=AsyncMock(side_effect=read), aput=AsyncMock(side_effect=write))
        self.manager = SandboxManager(self.store)
        self.addAsyncCleanup(self.close_manager)

    async def close_manager(self) -> None:
        if self.manager._close_task is None:
            await self.manager.close()
        else:
            # 覆盖关闭失败的测试已经完成对应断言。
            await asyncio.gather(self.manager._close_task, return_exceptions=True)

    async def ready_reserve(self) -> str:
        """
        等待明确请求的预热完成，不进行轮询或外部 IO。
        """
        await self.manager.initialize()
        await self.manager._warm_task
        self.assertIsNotNone(self.manager._warm_reserve)
        return self.manager._warm_reserve.id

    async def wait_for_thread(self, entered: threading.Event) -> None:
        self.assertTrue(await asyncio.to_thread(entered.wait, 3))

    async def test_startup_is_nonblocking_and_deduplicates_pending_seed(self) -> None:
        entered, release = threading.Event(), threading.Event()

        def seed(proxy):
            entered.set()
            self.assertTrue(release.wait(3))

        self.synchronizer.return_value.sync.side_effect = seed
        try:
            await asyncio.wait_for(self.manager.initialize(), 1)
            await self.wait_for_thread(entered)
            self.assertIsNone(self.manager._warm_reserve)
            first_task = self.manager._warm_task
            await asyncio.gather(*(self.manager.initialize() for _ in range(5)))
            self.assertIs(self.manager._warm_task, first_task)
            self.create.assert_called_once()
            self.store.aput.assert_not_awaited()
        finally:
            release.set()
            await self.manager._warm_task
        self.synchronizer.assert_called_once_with(
            SKILLS_ROOT, Path(__file__).resolve().parents[1] / "src/agent/memory/AGENTS.md",
        )
        self.assertEqual(self.create.call_args.kwargs["metadata"], {})

    async def test_disabled_prewarm_still_allows_demand_creation(self) -> None:
        with patch(f"{MODULE}.OPEN_SANDBOX_PREWARM_ENABLED", False):
            await self.manager.initialize()
            self.assertIsNone(self.manager._warm_task)
            proxy = await self.manager.get_backend("user")
        self.assertEqual(self.records["user"]["sandbox_id"], proxy.id)
        self.create.assert_called_once()
        self.assertEqual(self.create.call_args.kwargs["metadata"], {"myagent_user_id": "user"})

    async def test_startup_creation_failure_falls_back_without_retry_loop(self) -> None:
        create = self.create.side_effect
        self.create.side_effect = OSError("unavailable")
        await self.manager.initialize()
        await self.manager._warm_task
        self.assertIsNone(self.manager._warm_reserve)
        self.create.assert_called_once()
        self.create.side_effect = create
        proxy = await self.manager.get_backend("user")
        self.assertEqual(self.records["user"]["sandbox_id"], proxy.id)
        self.assertEqual(self.create.call_count, 2)

    async def test_failed_seed_is_never_visible_and_kills_only_its_reserve(self) -> None:
        self.synchronizer.return_value.sync.side_effect = RuntimeError("seed failed")
        await self.manager.initialize()
        await self.manager._warm_task
        self.assertIsNone(self.manager._warm_reserve)
        sandbox = next(iter(self.instances.values()))
        self.admin.kill_sandbox.assert_called_once_with(sandbox.id)
        sandbox.close.assert_called_once()
        self.store.aput.assert_not_awaited()
        self.assertEqual(self.manager._proxies, {})

    async def test_same_user_concurrency_creates_one_binding(self) -> None:
        proxies = await asyncio.gather(*(self.manager.get_backend("user") for _ in range(5)))
        self.assertTrue(all(proxy is proxies[0] for proxy in proxies))
        self.create.assert_called_once()
        self.store.aput.assert_awaited_once()

    async def test_persisted_identifier_wins_over_ready_reserve(self) -> None:
        reserve_id = await self.ready_reserve()
        stored = MagicMock(id="stored")
        self.instances[stored.id] = stored
        self.records["user"] = {"sandbox_id": stored.id}
        proxy = await self.manager.get_backend("user")
        self.assertEqual(proxy.id, "stored")
        self.connect.assert_called_once()
        self.assertEqual(self.manager._warm_reserve.id, reserve_id)
        self.create.assert_called_once()

    async def test_lookup_errors_do_not_claim_reserve_or_overwrite_identifier(self) -> None:
        reserve_id = await self.ready_reserve()
        self.records["user"] = {"sandbox_id": "stored"}
        self.admin.get_sandbox_info.side_effect = SandboxApiException(status_code=503)
        with self.assertRaises(SandboxApiException):
            await self.manager.get_backend("user")
        self.assertEqual(self.records["user"], {"sandbox_id": "stored"})
        self.assertEqual(self.manager._warm_reserve.id, reserve_id)
        self.store.aput.assert_not_awaited()
        self.create.assert_called_once()

    async def test_confirmed_gone_allows_atomic_reserve_claim(self) -> None:
        reserve_id = await self.ready_reserve()
        self.records["user"] = {"sandbox_id": "gone"}
        self.admin.get_sandbox_info.side_effect = SandboxApiException(status_code=404)
        proxy = await self.manager.get_backend("user")
        self.assertEqual(proxy.id, reserve_id)
        self.assertEqual(self.records["user"]["sandbox_id"], reserve_id)
        self.connect.assert_not_called()

    async def test_expired_idle_reserve_is_discarded_before_binding(self) -> None:
        reserve_id = await self.ready_reserve()
        self.instances[reserve_id].is_healthy.return_value = False
        self.admin.kill_sandbox.side_effect = SandboxApiException(status_code=404)
        proxy = await self.manager.get_backend("user")
        self.assertNotEqual(proxy.id, reserve_id)
        self.assertEqual(self.records["user"]["sandbox_id"], proxy.id)
        self.admin.kill_sandbox.assert_called_once_with(reserve_id)
        self.instances[reserve_id].close.assert_called_once()

    async def test_two_users_never_share_reserve_and_replenishment_is_deduplicated(self) -> None:
        reserve_id = await self.ready_reserve()
        entered, release = threading.Event(), threading.Event()

        def seed(proxy):
            entered.set()
            self.assertTrue(release.wait(3))

        self.synchronizer.return_value.sync.side_effect = seed
        try:
            proxies = await asyncio.gather(
                self.manager.get_backend("one"), self.manager.get_backend("two"),
            )
            await self.wait_for_thread(entered)
            self.assertNotEqual(proxies[0].id, proxies[1].id)
            self.assertIn(reserve_id, {proxy.id for proxy in proxies})
            warm_task = self.manager._warm_task
            await asyncio.gather(*(self.manager.initialize() for _ in range(5)))
            self.assertIs(self.manager._warm_task, warm_task)
            self.assertEqual(self.create.call_count, 3)
        finally:
            release.set()
            await self.manager._warm_task
        self.assertNotIn(self.manager._warm_reserve.id, {proxy.id for proxy in proxies})

    async def test_slow_user_sdk_io_does_not_serialize_other_users(self) -> None:
        entered, release = threading.Event(), threading.Event()
        create = self.create.side_effect

        def blocking_create(**kwargs):
            if kwargs["metadata"].get("myagent_user_id") == "slow":
                entered.set()
                self.assertTrue(release.wait(3))
            return create(**kwargs)

        self.create.side_effect = blocking_create
        slow = asyncio.create_task(self.manager.get_backend("slow"))
        try:
            await self.wait_for_thread(entered)
            fast = await asyncio.wait_for(self.manager.get_backend("fast"), 1)
            self.assertEqual(self.records["fast"]["sandbox_id"], fast.id)
        finally:
            release.set()
            await slow

    async def test_uncertain_commit_never_returns_claimed_instance_to_pool(self) -> None:
        reserve_id = await self.ready_reserve()
        write = self.store.aput.side_effect

        async def committed_then_failed(*args, **kwargs):
            await write(*args, **kwargs)
            raise OSError("acknowledgement lost")

        self.store.aput.side_effect = committed_then_failed
        with self.assertRaises(OSError):
            await self.manager.get_backend("one")
        self.instances[reserve_id].close.assert_called_once()
        self.store.aput.side_effect = write
        other = await self.manager.get_backend("two")
        self.assertNotEqual(other.id, reserve_id)
        recovered = await self.manager.get_backend("one")
        self.assertEqual(recovered.id, reserve_id)
        self.assertNotIn(call(reserve_id), self.admin.kill_sandbox.call_args_list)

    async def test_cancelled_commit_preserves_binding_and_never_reassigns_claim(self) -> None:
        reserve_id = await self.ready_reserve()
        entered = asyncio.Event()
        write = self.store.aput.side_effect

        async def committed_then_wait(*args, **kwargs):
            await write(*args, **kwargs)
            entered.set()
            await asyncio.Event().wait()

        self.store.aput.side_effect = committed_then_wait
        request = asyncio.create_task(self.manager.get_backend("one"))
        await asyncio.wait_for(entered.wait(), 2)
        request.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await request
        self.instances[reserve_id].close.assert_called_once()
        self.store.aput.side_effect = write
        other = await self.manager.get_backend("two")
        self.assertNotEqual(other.id, reserve_id)
        self.assertEqual(self.records["one"]["sandbox_id"], reserve_id)
        self.assertNotIn(call(reserve_id), self.admin.kill_sandbox.call_args_list)

    async def test_cancelled_demand_creation_and_close_drain_eventual_client(self) -> None:
        entered, release = threading.Event(), threading.Event()
        create = self.create.side_effect

        def blocking_create(**kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            return create(**kwargs)

        self.create.side_effect = blocking_create
        request = asyncio.create_task(self.manager.get_backend("user"))
        try:
            await self.wait_for_thread(entered)
            request.cancel()
            await asyncio.sleep(0)
            request.cancel()
            closing = asyncio.create_task(self.manager.close())
            await asyncio.sleep(0)
            self.assertFalse(closing.done())
        finally:
            release.set()
            with self.assertRaises(asyncio.CancelledError):
                await request
        await closing
        next(iter(self.instances.values())).close.assert_called_once()
        self.admin.kill_sandbox.assert_not_called()
        self.store.aput.assert_not_awaited()

    async def test_close_during_seed_waits_kills_reserve_and_rejects_new_work(self) -> None:
        entered, release = threading.Event(), threading.Event()

        def seed(proxy):
            entered.set()
            self.assertTrue(release.wait(3))

        self.synchronizer.return_value.sync.side_effect = seed
        await self.manager.initialize()
        try:
            await self.wait_for_thread(entered)
            closing = asyncio.create_task(self.manager.close())
            await asyncio.sleep(0)
            self.assertFalse(closing.done())
            for operation in (self.manager.initialize(), self.manager.get_backend("late")):
                with self.assertRaisesRegex(RuntimeError, "已关闭"):
                    await operation
            closing.cancel()
            await asyncio.sleep(0)
            closing.cancel()
            await asyncio.sleep(0)
            self.assertFalse(closing.done())
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await closing
        sandbox = next(iter(self.instances.values()))
        self.admin.kill_sandbox.assert_called_once_with(sandbox.id)
        sandbox.close.assert_called_once()
        self.assertIsNone(self.manager._warm_reserve)
        await self.manager.close()

    async def test_cancelled_prewarm_drains_creation_before_discard(self) -> None:
        entered, release = threading.Event(), threading.Event()
        create = self.create.side_effect

        def blocking_create(**kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            return create(**kwargs)

        self.create.side_effect = blocking_create
        await self.manager.initialize()
        try:
            await self.wait_for_thread(entered)
            self.manager._warm_task.cancel()
            await asyncio.sleep(0)
            self.manager._warm_task.cancel()
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await self.manager._warm_task
        sandbox = next(iter(self.instances.values()))
        sandbox.close.assert_called_once()
        self.admin.kill_sandbox.assert_called_once_with(sandbox.id)
        self.assertIsNone(self.manager._warm_reserve)

    async def test_renew_failure_preserves_cached_proxy_and_stored_id(self) -> None:
        proxy = await self.manager.get_backend("user")
        identifier = proxy.id
        self.admin.renew_sandbox.side_effect = SandboxApiException(status_code=404)
        again = await self.manager.get_backend("user")
        self.assertIs(again, proxy)
        self.assertEqual(self.records["user"]["sandbox_id"], identifier)
        self.create.assert_called_once()
        self.store.aput.assert_awaited_once()
        self.admin.renew_sandbox.assert_called_with(
            identifier, timedelta(seconds=OPEN_SANDBOX_SANDBOX_TIMEOUT_SECONDS),
        )
        self.assertEqual(self.admin.close.call_count, 2)

    async def test_renew_failure_after_reconnect_keeps_original_id(self) -> None:
        stored = MagicMock(id="stored")
        self.instances[stored.id] = stored
        self.records["user"] = {"sandbox_id": stored.id}
        self.admin.renew_sandbox.side_effect = OSError("renew failed")
        proxy = await self.manager.get_backend("user")
        self.assertEqual(proxy.id, stored.id)
        self.assertEqual(self.records["user"]["sandbox_id"], stored.id)
        self.create.assert_not_called()
        self.admin.kill_sandbox.assert_not_called()

    async def test_shutdown_kills_only_unclaimed_reserve_and_closes_all_clients(self) -> None:
        claimed_id = await self.ready_reserve()
        await self.manager.get_backend("user")
        await self.manager._warm_task
        reserve_id = self.manager._warm_reserve.id
        await asyncio.gather(self.manager.close(), self.manager.close())
        self.admin.kill_sandbox.assert_called_once_with(reserve_id)
        self.instances[claimed_id].close.assert_called_once()
        self.instances[reserve_id].close.assert_called_once()
        self.assertEqual(self.records["user"]["sandbox_id"], claimed_id)

    async def test_reserve_kill_failure_still_closes_every_client(self) -> None:
        claimed_id = await self.ready_reserve()
        await self.manager.get_backend("user")
        await self.manager._warm_task
        reserve_id = self.manager._warm_reserve.id
        self.admin.kill_sandbox.side_effect = OSError("kill failed")
        with self.assertRaises(OSError):
            await self.manager.close()
        for identifier in (claimed_id, reserve_id):
            self.instances[identifier].close.assert_called_once()
        # 幂等关闭会为调用方保留原始清理失败。
        with self.assertRaises(OSError):
            await self.manager.close()
