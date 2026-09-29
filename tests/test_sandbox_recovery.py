"""沙箱恢复、同步和客户端归属的回归测试。"""

from __future__ import annotations

import asyncio
import json
import shlex
import threading
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from deepagents.backends.protocol import ExecuteResponse, FileDownloadResponse, FileUploadResponse
from deepagents.middleware.skills import SkillsMiddleware
from langgraph.types import Command
from opensandbox.exceptions import SandboxApiException, SandboxException

from agent.backends.sandbox_manager import SandboxManager
from agent.backends.open_sandbox import OpenSandboxBackend
from agent.backends.sandbox_proxy import SandboxBackendProxy
from agent.backends.skill_sync import SANDBOX_MANIFEST_PATH, SandboxSkillSynchronizer
from agent.middlewares.skills_sync import SandboxSkillsMiddleware
from agent.tools.async_sandbox_tools import create_async_sandbox_tools


class SkillSyncTests(unittest.TestCase):
    """失败时必须保留之前的 manifest，且绝不能执行不安全路径。"""

    def setUp(self) -> None:
        self.files = {}
        self.backend = MagicMock()
        self.backend.download_files.side_effect = lambda paths: [
            FileDownloadResponse(
                path=path, content=self.files.get(path),
                error=None if path in self.files else "file_not_found",
            ) for path in paths
        ]
        self.backend.upload_files.side_effect = self.upload
        self.backend.execute.return_value = ExecuteResponse("", 0)
        self.proxy = SandboxBackendProxy(self.backend)
        self.sync = SandboxSkillSynchronizer(Path("unused"), Path("unused"))
        self.local = {"/skills/main/demo/SKILL.md": b"demo"}
        self.sync._local_files = lambda: self.local

    def upload(self, files):
        self.files.update(files)
        return [FileUploadResponse(path=path) for path, _ in files]

    def test_failed_upload_is_retried_before_manifest_commit(self) -> None:
        self.backend.upload_files.side_effect = lambda files: [
            FileUploadResponse(path=path, error="permission_denied") for path, _ in files
        ]
        with self.assertRaises(RuntimeError):
            self.sync.sync(self.proxy)
        self.assertNotIn(SANDBOX_MANIFEST_PATH, self.files)
        self.backend.upload_files.side_effect = self.upload
        self.assertTrue(self.sync.sync(self.proxy))
        self.assertEqual(self.files["/skills/main/demo/SKILL.md"], b"demo")
        self.assertFalse(self.sync.sync(self.proxy))

    def test_missing_upload_acknowledgement_does_not_commit(self) -> None:
        self.backend.upload_files.side_effect = lambda files: []
        with self.assertRaises(RuntimeError):
            self.sync.sync(self.proxy)
        self.assertNotIn(SANDBOX_MANIFEST_PATH, self.files)

    def test_manifest_read_failure_preserves_deletion_tracking_for_retry(self) -> None:
        self.sync.sync(self.proxy)
        previous = self.files[SANDBOX_MANIFEST_PATH]
        self.local = {}
        download = self.backend.download_files.side_effect
        self.backend.reset_mock()
        for error in ("download_failed: timeout", "permission_denied"):
            self.backend.download_files.side_effect = lambda paths: [
                FileDownloadResponse(path=paths[0], error=error),
            ]
            with self.assertRaises(RuntimeError):
                self.sync.sync(self.proxy)
            self.assertEqual(self.files[SANDBOX_MANIFEST_PATH], previous)
            self.backend.upload_files.assert_not_called()
            self.backend.execute.assert_not_called()
        self.backend.download_files.side_effect = download
        self.assertTrue(self.sync.sync(self.proxy))
        self.assertEqual(
            shlex.split(self.backend.execute.call_args.args[0]),
            ["rm", "-f", "--", "/skills/main/demo/SKILL.md"],
        )
        self.assertEqual(json.loads(self.files[SANDBOX_MANIFEST_PATH]), {})

    def test_malformed_or_missing_manifest_content_never_resets_tracking(self) -> None:
        for content in (b"{broken", b"\xff", b"[]", b"null", b"", None):
            self.backend.download_files.side_effect = lambda paths: [
                FileDownloadResponse(path=paths[0], content=content),
            ]
            with self.assertRaises(RuntimeError):
                self.sync.sync(self.proxy)
            self.backend.upload_files.assert_not_called()
            self.backend.execute.assert_not_called()

    def test_failed_delete_retains_manifest_and_retries(self) -> None:
        self.sync.sync(self.proxy)
        previous = self.files[SANDBOX_MANIFEST_PATH]
        self.local = {}
        for exit_code in (1, None):
            self.backend.execute.return_value = ExecuteResponse("failed", exit_code)
            with self.assertRaises(RuntimeError):
                self.sync.sync(self.proxy)
            self.assertEqual(self.files[SANDBOX_MANIFEST_PATH], previous)
        self.backend.execute.return_value = ExecuteResponse("", 0)
        self.assertTrue(self.sync.sync(self.proxy))
        self.assertEqual(json.loads(self.files[SANDBOX_MANIFEST_PATH]), {})

    def test_manifest_paths_are_constrained_and_shell_quoted(self) -> None:
        self.local = {}
        for path in ("/tmp/victim", "/skills/../victim", "/skills//victim", "/skills/", "/skills/main/../../victim"):
            self.files[SANDBOX_MANIFEST_PATH] = json.dumps({path: "old"}).encode()
            with self.assertRaises(RuntimeError):
                self.sync.sync(self.proxy)
        self.backend.execute.assert_not_called()
        path = "/skills/main/$(touch nope)`echo no`'file"
        self.files[SANDBOX_MANIFEST_PATH] = json.dumps({path: "old"}).encode()
        self.sync.sync(self.proxy)
        self.assertEqual(shlex.split(self.backend.execute.call_args.args[0]), ["rm", "-f", "--", path])

    def test_concurrent_syncs_share_proxy_transaction(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        original = self.upload

        def upload(files):
            if files[0][0] != SANDBOX_MANIFEST_PATH:
                entered.set()
                self.assertTrue(release.wait(3))
            return original(files)

        self.backend.upload_files.side_effect = upload
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.sync.sync, self.proxy)
            self.assertTrue(entered.wait(3))
            second = pool.submit(self.sync.sync, self.proxy)
            release.set()
            self.assertTrue(first.result(3))
            self.assertFalse(second.result(3))
        self.assertEqual(self.backend.upload_files.call_count, 2)

    def test_host_symlinks_cannot_leak_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "skills"
            root.mkdir()
            outside = base / "private"
            outside.mkdir()
            (outside / "secret").write_bytes(b"must not upload")
            agents = base / "AGENTS.md"
            agents.write_bytes(b"instructions")
            synchronizer = SandboxSkillSynchronizer(root, agents)
            for target in (outside / "secret", outside):
                link = root / "linked"
                try:
                    link.symlink_to(target, target_is_directory=target.is_dir())
                except OSError as error:
                    self.skipTest(f"Host does not permit test symlinks: {error}")
                try:
                    with self.assertRaisesRegex(ValueError, "符号链接"):
                        synchronizer.sync(self.proxy)
                    self.backend.upload_files.assert_not_called()
                finally:
                    link.unlink()

    def test_resolved_escape_is_rejected_even_without_symlink_flag(self) -> None:
        path = Path("skills/file")
        root = Path("skills").resolve()
        with patch.object(Path, "is_symlink", return_value=False), patch.object(
            Path, "is_junction", return_value=False,
        ), patch.object(Path, "resolve", return_value=root.parent / "private"):
            with self.assertRaises(ValueError):
                SandboxSkillSynchronizer._validate_local_path(path, root)

    def test_link_flags_stop_scan_before_reading_or_uploading_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            root = base / "skills"
            root.mkdir()
            agents = base / "AGENTS.md"
            agents.write_bytes(b"instructions")
            linked_file = root / "linked-file"
            linked_file.write_bytes(b"secret")
            linked_directory = root / "linked-directory"
            linked_directory.mkdir()
            (linked_directory / "secret").write_bytes(b"secret")
            synchronizer = SandboxSkillSynchronizer(root, agents)
            read_bytes = Path.read_bytes
            for target, flag in ((linked_file, "is_symlink"), (linked_directory, "is_symlink"), (linked_directory, "is_junction")):
                with patch.object(Path, flag, autospec=True, side_effect=lambda path: path == target), patch.object(
                    Path, "read_bytes", autospec=True, side_effect=read_bytes,
                ) as read:
                    with self.assertRaises(ValueError):
                        synchronizer.sync(self.proxy)
                    for call in read.call_args_list:
                        self.assertNotEqual(call.args[0], target)
                        self.assertNotEqual(call.args[0], linked_directory / "secret")
                    self.backend.upload_files.assert_not_called()


class ProxyLifetimeTests(unittest.TestCase):
    """替换和关闭必须等待正在执行的 SDK 调用完成。"""

    def test_replacement_waits_and_closes_each_client_once(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        first = MagicMock(id="old")
        second = MagicMock(id="new")

        def execute(*args, **kwargs):
            entered.set()
            self.assertTrue(release.wait(3))
            first.close.assert_not_called()
            return ExecuteResponse("ok", 0)

        first.execute.side_effect = execute
        proxy = SandboxBackendProxy(first)
        with ThreadPoolExecutor(max_workers=2) as pool:
            execution = pool.submit(proxy.execute, "command")
            self.assertTrue(entered.wait(3))
            replacement = pool.submit(proxy.replace_backend, second)
            first.close.assert_not_called()
            release.set()
            execution.result(3)
            replacement.result(3)
        self.assertEqual(proxy.id, "new")
        first.close.assert_called_once()
        proxy.close()
        proxy.close()
        second.close.assert_called_once()


class SandboxAsyncTests(unittest.IsolatedAsyncioTestCase):
    """异步入口必须保持响应能力，并刷新用户资源。"""

    async def test_task_uses_replacement_id(self) -> None:
        """异步启动必须同时保留共享沙箱和框架可查询的任务状态。"""
        proxy = SandboxBackendProxy(MagicMock(id="old"))
        task = create_async_sandbox_tools(
            [{"name": "chart", "url": "unused", "graph_id": "graph"}], sandbox_backend=proxy,
        )[0]
        proxy.replace_backend(MagicMock(id="new"))
        client = SimpleNamespace(
            threads=SimpleNamespace(create=AsyncMock(return_value={"thread_id": "task"})),
            runs=SimpleNamespace(create=AsyncMock(return_value={"run_id": "run-1"})),
        )
        with patch("agent.tools.async_sandbox_tools.get_client", return_value=client):
            result = await task.coroutine(
                "chart",
                "chart",
                SimpleNamespace(tool_call_id="call-1"),
            )
        self.assertEqual(client.runs.create.call_args.kwargs["context"], {"sandbox_id": "new"})
        self.assertIsInstance(result, Command)
        tracked_task = result.update["async_tasks"]["task"]
        self.assertEqual(tracked_task["agent_name"], "chart")
        self.assertEqual(tracked_task["run_id"], "run-1")
        self.assertEqual(tracked_task["status"], "running")

    async def test_cached_health_probe_is_off_event_loop_and_manager_closes(self) -> None:
        with patch("agent.backends.sandbox_manager.OPEN_SANDBOX_API_KEY", "test"):
            manager = SandboxManager(MagicMock())
        main_thread = threading.get_ident()
        backend = MagicMock(id="sandbox")
        backend.is_healthy.side_effect = lambda: self.assertNotEqual(threading.get_ident(), main_thread) or True
        proxy = SandboxBackendProxy(backend)
        manager._proxies["user"] = proxy
        with patch.object(manager, "_renew_on_access"):
            self.assertIs(await manager.get_backend("user"), proxy)
        await manager.close()
        await manager.close()
        backend.close.assert_called_once()
        backend.kill.assert_not_called()

    async def test_persistence_failure_closes_new_backend(self) -> None:
        store = SimpleNamespace(aput=AsyncMock(side_effect=RuntimeError("database failed")))
        with patch("agent.backends.sandbox_manager.OPEN_SANDBOX_API_KEY", "test"):
            manager = SandboxManager(store)
        backend = MagicMock()
        manager._resolve_backend = AsyncMock(return_value=(backend, "sandbox"))
        with patch.object(manager, "_renew_on_access"):
            with self.assertRaisesRegex(RuntimeError, "database failed"):
                await manager.get_backend("user")
        backend.close.assert_called_once()
        self.assertEqual(manager._proxies, {})

    async def test_cancellation_closes_client_created_by_worker_thread(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        backend = MagicMock()
        store = SimpleNamespace(aget=AsyncMock(return_value=None))
        with patch("agent.backends.sandbox_manager.OPEN_SANDBOX_API_KEY", "test"):
            manager = SandboxManager(store)

        def connect(*args):
            entered.set()
            if not release.wait(3):
                raise TimeoutError("test release missing")
            return backend

        manager._create_backend = connect
        task = asyncio.create_task(manager.get_backend("user"))
        self.assertTrue(await asyncio.to_thread(entered.wait, 3))
        task.cancel()
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        backend.close.assert_called_once()

    async def test_unhealthy_reconnection_closes_client(self) -> None:
        with patch("agent.backends.sandbox_manager.OPEN_SANDBOX_API_KEY", "test"):
            manager = SandboxManager(MagicMock())
        stale = MagicMock(id="stale")
        stale.is_healthy.return_value = False
        with patch("agent.backends.sandbox_manager.SandboxSync.connect", return_value=stale), patch(
            "agent.backends.sandbox_manager.SandboxSync.create",
        ) as create, patch.object(manager, "_is_confirmed_gone", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "稍后重试"):
                await asyncio.to_thread(manager._connect_existing, "old")
        stale.close.assert_called_once()
        create.assert_not_called()

    async def test_transient_failures_preserve_persisted_id_and_proxy(self) -> None:
        record = {"sandbox_id": "original"}
        store = SimpleNamespace(aget=AsyncMock(return_value=SimpleNamespace(value=record)), aput=AsyncMock())
        with patch("agent.backends.sandbox_manager.OPEN_SANDBOX_API_KEY", "test"):
            manager = SandboxManager(store)
        proxy = SandboxBackendProxy(MagicMock(id="original"))
        proxy._backend.is_healthy.return_value = False
        manager._proxies["user"] = proxy
        admin = MagicMock()
        for error in (SandboxApiException("unavailable", status_code=503), SandboxException("timeout")):
            for phase in ("lookup", "connect"):
                admin.get_sandbox_info.side_effect = error if phase == "lookup" else None
                admin.get_sandbox_info.return_value = SimpleNamespace(status=SimpleNamespace(state="Running"))
                with patch("agent.backends.sandbox_manager.SandboxManagerSync.create", return_value=admin), patch(
                    "agent.backends.sandbox_manager.SandboxSync.connect", side_effect=error,
                ), patch("agent.backends.sandbox_manager.SandboxSync.create") as create:
                    with self.assertRaises(type(error)):
                        await manager.get_backend("user")
                create.assert_not_called()
                store.aput.assert_not_called()
                self.assertEqual(record["sandbox_id"], "original")
                self.assertIs(manager._proxies["user"], proxy)
                proxy._backend.close.assert_not_called()
        self.assertEqual(admin.close.call_count, 4)

    async def test_only_confirmed_absence_or_termination_allows_replacement(self) -> None:
        store = SimpleNamespace(
            aget=AsyncMock(return_value=SimpleNamespace(value={"sandbox_id": "old"})),
        )
        with patch("agent.backends.sandbox_manager.OPEN_SANDBOX_API_KEY", "test"):
            manager = SandboxManager(store)
        admin = MagicMock()
        fresh = MagicMock(id="fresh")
        for state in ("missing", "Terminated", "Failed", "Paused", "Stopping"):
            admin.get_sandbox_info.side_effect = SandboxApiException(status_code=404) if state == "missing" else None
            admin.get_sandbox_info.return_value = SimpleNamespace(status=SimpleNamespace(state=state))
            with patch("agent.backends.sandbox_manager.SandboxManagerSync.create", return_value=admin), patch(
                "agent.backends.sandbox_manager.SandboxSync.connect", side_effect=SandboxException("not ready"),
            ) as connect, patch("agent.backends.sandbox_manager.SandboxSync.create", return_value=fresh) as create:
                if state in {"missing", "Terminated", "Failed"}:
                    backend, identifier = await manager._resolve_backend("user")
                    self.assertEqual(identifier, "fresh")
                    create.assert_called_once()
                    connect.assert_not_called()
                    backend.close()
                else:
                    with self.assertRaises(SandboxException):
                        await manager._resolve_backend("user")
                    create.assert_not_called()

    async def test_every_thread_refreshes_even_when_sync_reports_no_changes(self) -> None:
        synchronizer = MagicMock()
        synchronizer.sync.return_value = False
        middleware = SandboxSkillsMiddleware(backend=SandboxBackendProxy(), sources=[], synchronizer=synchronizer)
        state = {"skills_metadata": [{"name": "old"}], "skills_load_errors": ["old error"]}
        with patch.object(SkillsMiddleware, "abefore_agent", new=AsyncMock(return_value={"skills_metadata": []})) as parent:
            for _ in range(2):
                result = await middleware.abefore_agent(state, None, {})
                self.assertEqual(result, {"skills_metadata": [], "skills_load_errors": []})
                self.assertNotIn("skills_metadata", parent.call_args.args[0])
        self.assertEqual(state["skills_metadata"], [{"name": "old"}])


class OpenSandboxBackendTests(unittest.TestCase):
    """验证 SDK 结果会转换为 DeepAgents 原语。"""

    def test_only_sdk_404_is_normalized_as_missing_file(self) -> None:
        """
        保持传输、权限和服务器错误与文件缺失错误相互区分。
        """
        sandbox = MagicMock(id="sandbox")
        backend = OpenSandboxBackend(sandbox, 30)
        for error, expected in (
            (SandboxApiException(status_code=404), "file_not_found"),
            (SandboxApiException(status_code=403), "permission_denied"),
            (SandboxApiException(status_code=503), "download_failed:"),
            (TimeoutError("file_not_found"), "download_failed:"),
        ):
            sandbox.files.read_bytes.side_effect = error
            result = backend.download_files(["/manifest"])[0]
            self.assertTrue(result.error.startswith(expected))
            if expected != "file_not_found":
                self.assertNotEqual(result.error, "file_not_found")

    def test_executes_and_transfers_binary_files(self) -> None:
        sandbox = MagicMock()
        sandbox.id = "sandbox-1"
        execution = MagicMock(exit_code=0)
        execution.__str__.return_value = "ok"
        sandbox.commands.run.return_value = execution
        sandbox.files.read_bytes.return_value = b"\x00data"
        backend = OpenSandboxBackend(sandbox, 30)

        self.assertEqual(backend.id, "sandbox-1")
        self.assertEqual(backend.execute("echo ok").output, "ok")
        self.assertEqual(backend.upload_files([("/tmp/a", b"x")])[0].error, None)
        self.assertEqual(backend.download_files(["/tmp/a"])[0].content, b"\x00data")
        sandbox.get_info.assert_not_called()
        self.assertEqual(sandbox.files.write_files.call_args.args[0][0].mode, 644)


class SandboxProxyTests(unittest.TestCase):
    """图持有的代理必须使用替换后的后端，而不需要重新创建。"""

    def test_replaces_active_backend(self) -> None:
        first = MagicMock(id="first")
        first.execute.return_value = ExecuteResponse("first", 0)
        second = MagicMock(id="second")
        second.execute.return_value = ExecuteResponse("second", 0)
        proxy = SandboxBackendProxy(first)

        proxy.replace_backend(second)

        self.assertEqual(proxy.id, "second")
        self.assertEqual(proxy.execute("true").output, "second")


class SandboxSkillSynchronizerTests(unittest.TestCase):
    """技能变更必须在模型发现前增量上传。"""

    def test_uploads_only_changed_files_and_removes_deleted_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "skills"
            skill = root / "main" / "example" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("---\nname: example\ndescription: test\n---\n", encoding="utf-8")
            agents = Path(temporary_directory) / "AGENTS.md"
            agents.write_text("instructions", encoding="utf-8")
            backend = MagicMock()
            backend.download_files.return_value = [SimpleNamespace(path=SANDBOX_MANIFEST_PATH, error="file_not_found", content=None)]
            backend.upload_files.side_effect = lambda files: [
                SimpleNamespace(path=path, error=None) for path, _ in files
            ]
            backend.execute.return_value = ExecuteResponse("", 0)
            synchronizer = SandboxSkillSynchronizer(root, agents)

            self.assertTrue(synchronizer.sync(backend))
            uploaded = dict(backend.upload_files.call_args.args[0])
            manifest = json.loads(uploaded[SANDBOX_MANIFEST_PATH])
            self.assertIn("/skills/main/example/SKILL.md", manifest)

            backend.reset_mock()
            backend.download_files.return_value = [
                SimpleNamespace(path=SANDBOX_MANIFEST_PATH, error=None, content=uploaded[SANDBOX_MANIFEST_PATH])
            ]
            self.assertFalse(synchronizer.sync(backend))
            backend.upload_files.assert_not_called()

            skill.unlink()
            self.assertTrue(synchronizer.sync(backend))
            backend.execute.assert_called_once()
