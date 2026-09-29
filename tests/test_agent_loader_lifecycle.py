"""AgentLoader 的初始化回滚、资源释放及用户级并发回归测试。"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from api.agent_loader import AgentLoader


class AgentLoaderLifecycleTests(unittest.IsolatedAsyncioTestCase):
    """不连接外部资源，验证生命周期内的所有权和清理边界。"""

    async def test_concurrent_initialization_builds_once(self) -> None:
        loader = AgentLoader()
        persistence = AsyncMock(return_value=(object(), object()))
        with (
            patch.dict("sys.modules", {"agent.main_agent": SimpleNamespace(create_main_agent=AsyncMock())}),
            patch("api.agent_loader.create_async_persistence", persistence),
            patch("api.agent_loader.SandboxManager") as manager,
            patch("api.agent_loader.ThreadHistoryReader") as reader,
        ):
            manager.return_value.initialize = AsyncMock()
            await asyncio.gather(loader.initialize(), loader.initialize())
        persistence.assert_awaited_once()
        manager.assert_called_once()
        manager.return_value.initialize.assert_awaited_once()
        reader.assert_called_once()
        self.assertTrue(loader._initialized)

    async def test_failed_reader_initialization_closes_acquired_resources(self) -> None:
        loader = AgentLoader()
        store, checkpointer = object(), object()
        manager = SimpleNamespace(initialize=AsyncMock(), close=AsyncMock())
        with (
            patch.dict("sys.modules", {"agent.main_agent": SimpleNamespace(create_main_agent=AsyncMock())}),
            patch("api.agent_loader.create_async_persistence", new=AsyncMock(return_value=(store, checkpointer))),
            patch("api.agent_loader.SandboxManager", return_value=manager),
            patch("api.agent_loader.ThreadHistoryReader", side_effect=ValueError("invalid graph")),
            patch("api.agent_loader.close_async_persistence", new=AsyncMock()) as close,
        ):
            with self.assertRaises(ValueError):
                await loader.initialize()
        manager.close.assert_awaited_once()
        close.assert_awaited_once_with(store, checkpointer)
        self.assertFalse(loader._initialized)
        self.assertIsNone(loader._store)

    async def test_shutdown_closes_database_even_when_manager_close_fails(self) -> None:
        loader = AgentLoader()
        loader._initialized = True
        store, checkpointer = object(), object()
        loader._store, loader._checkpointer = store, checkpointer
        loader._sandbox_manager = SimpleNamespace(close=AsyncMock(side_effect=OSError("close failed")))
        with patch("api.agent_loader.close_async_persistence", new=AsyncMock()) as close:
            with self.assertRaises(OSError):
                await loader.shutdown()
        close.assert_awaited_once_with(store, checkpointer)
        self.assertFalse(loader._initialized)

    async def test_slow_user_does_not_block_another_user(self) -> None:
        loader = AgentLoader()
        loader._initialized = True
        loader._store, loader._checkpointer = object(), object()
        loader._agent_factory = AsyncMock(side_effect=lambda *args, **kwargs: object())
        entered, release = asyncio.Event(), asyncio.Event()

        async def backend(user_id):
            if user_id == "slow":
                entered.set()
                await release.wait()
            return object()

        loader._sandbox_manager = SimpleNamespace(get_backend=backend)
        slow = asyncio.create_task(loader.get_agent_for_user("slow", "slow", "t1"))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            other = await asyncio.wait_for(loader.get_agent_for_user("other", "other", "t2"), 2)
            self.assertIsNotNone(other)
        finally:
            release.set()
            await slow
        self.assertEqual(loader._agent_factory.await_count, 2)

    async def test_concurrent_same_user_builds_one_agent(self) -> None:
        loader = AgentLoader()
        loader._initialized = True
        loader._store, loader._checkpointer = object(), object()
        loader._agent_factory = AsyncMock(return_value=object())
        loader._sandbox_manager = SimpleNamespace(get_backend=AsyncMock(return_value=object()))
        agents = await asyncio.gather(
            loader.get_agent_for_user("u1", "user", "t1"),
            loader.get_agent_for_user("u1", "user", "t2"),
        )
        self.assertIs(agents[0], agents[1])
        loader._agent_factory.assert_awaited_once()
        self.assertEqual(loader._user_groups["u1"].thread_ids, {"t1", "t2"})


class PersistenceLifecycleTests(unittest.IsolatedAsyncioTestCase):
    """数据库资源的部分初始化失败和关闭异常回归。"""

    async def test_second_connection_failure_closes_first(self) -> None:
        """
        第二次建连失败时不能遗留第一个数据库连接。
        """
        first = SimpleNamespace(close=AsyncMock())
        with patch("psycopg.AsyncConnection.connect", AsyncMock(side_effect=[first, OSError("offline")])):
            with self.assertRaises(OSError):
                from agent.config import create_async_persistence

                await create_async_persistence()
        first.close.assert_awaited_once()

    async def test_setup_cancellation_closes_both_connections(self) -> None:
        """
        取消初始化时，所有已建立的连接仍必须被回收。
        """
        first = SimpleNamespace(close=AsyncMock())
        second = SimpleNamespace(close=AsyncMock())
        with (
            patch("psycopg.AsyncConnection.connect", AsyncMock(side_effect=[first, second])),
            patch("langgraph.store.postgres.aio.AsyncPostgresStore") as store,
            patch("langgraph.checkpoint.postgres.aio.AsyncPostgresSaver") as saver,
        ):
            store.return_value.setup = AsyncMock()
            saver.return_value.setup = AsyncMock(side_effect=asyncio.CancelledError())
            with self.assertRaises(asyncio.CancelledError):
                from agent.config import create_async_persistence

                await create_async_persistence()
        first.close.assert_awaited_once()
        second.close.assert_awaited_once()

    async def test_close_failure_does_not_skip_other_connection(self) -> None:
        """
        一个连接关闭报错不影响另一个连接的回收。
        """
        first = SimpleNamespace(conn=SimpleNamespace(close=AsyncMock()))
        second = SimpleNamespace(conn=SimpleNamespace(close=AsyncMock(side_effect=OSError("closed"))))
        with self.assertRaises(OSError):
            from agent.config import close_async_persistence

            await close_async_persistence(first, second)
        first.conn.close.assert_awaited_once()
