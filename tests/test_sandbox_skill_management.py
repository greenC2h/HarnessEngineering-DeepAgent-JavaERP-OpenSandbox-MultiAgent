"""以隔离文件系统模拟沙箱，验证工具的传输、持久化与失败恢复。"""

import asyncio
from contextlib import nullcontext
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4
import zipfile

from agent.tools.skill_tools import SKILL_MANAGEMENT_SCRIPT, _skill_management_script
from agent.tools.sandbox_skill_management import MAX_BYTES, _local_path, _runtime_package
from agent.backends.skill_sync import SANDBOX_MANIFEST_PATH, SandboxSkillSynchronizer


def verify_real_sandbox_skill_flow(backend, subagent_name: str = "procurement_order") -> dict:
    """
    显式调用才执行真实沙箱验证；本地使用临时根，远端只操作唯一测试技能。

    异步主流程应通过 asyncio.to_thread 调用，传入当前已连接的沙箱代理。
    返回成功前验证创建、主 Agent 安装、子 Agent 分配、查询和双端删除。
    """
    _skill_management_script._skill_directory(Path("."), subagent_name)
    name = "smoke-" + uuid4().hex
    main_path = f"/skills/main/{name}"
    target_path = f"/skills/subagents/{subagent_name}/{name}"
    create_code = (
        "from pathlib import Path; "
        f"p=Path({main_path!r}); p.mkdir(parents=True,exist_ok=False); "
        f"(p/'SKILL.md').write_text('---\\nname: {name}\\ndescription: isolated integration probe\\n---\\n',encoding='utf-8'); "
        "(p/'resource.txt').write_text('sandbox-created',encoding='utf-8')"
    )
    with backend.transaction() if hasattr(backend, "transaction") else nullcontext():
        try:
            response = backend.execute("python3 -I -c " + shlex.quote(create_code))
            assert response.exit_code == 0, "sandbox fixture creation failed"
            with tempfile.TemporaryDirectory(prefix="skill-integration-") as temporary:
                local = Path(temporary) / "skills"
                tools = _skill_management_script.create_skill_management_tools(
                    local, {subagent_name}, sandbox_backend=backend)
                result = tools[1].invoke({"skill_name": name, "subagent_name": "main"})
                assert json.loads(result)["ok"], result
                assert (local / "main" / name / "resource.txt").read_text() == "sandbox-created"
                result = tools[1].invoke({"skill_name": name, "subagent_name": subagent_name})
                assert json.loads(result)["ok"], result
                assert not (local / "main" / name).exists()
                assert (local / "subagents" / subagent_name / name / "resource.txt").is_file()
                listing = json.loads(tools[2].invoke({"subagent_name": subagent_name}))
                assert any(item["skill_name"] == name for item in listing[subagent_name])
                result = tools[3].invoke({"skill_name": name, "subagent_name": subagent_name})
                assert json.loads(result)["ok"], result
                assert not (local / "subagents" / subagent_name / name).exists()
                check_code = f"from pathlib import Path; assert not Path({main_path!r}).exists(); assert not Path({target_path!r}).exists()"
                assert backend.execute("python3 -I -c " + shlex.quote(check_code)).exit_code == 0
            return {"ok": True, "skill_name": name,
                    "verified": ["sandbox creation", "main persistence", "subagent allocation", "metadata query", "two-sided deletion"]}
        finally:
            # 仅清除本次 UUID 技能，保留其他已安装技能和代理生命周期。
            cleanup_code = (
                "import shutil; from pathlib import Path; "
                f"paths=[Path({main_path!r}),Path({target_path!r})]; "
                "[(p.unlink() if p.is_symlink() else shutil.rmtree(p)) for p in paths if p.exists() or p.is_symlink()]"
            )
            cleanup = backend.execute("python3 -I -c " + shlex.quote(cleanup_code))
            if cleanup.exit_code != 0:
                raise RuntimeError("isolated sandbox skill cleanup failed: " + name)


def load_runtime():
    """仅加载仓库内可信运行器，技能脚本始终不执行。"""
    spec = importlib.util.spec_from_file_location("test_skill_runtime", SKILL_MANAGEMENT_SCRIPT.with_name("sandbox_runtime.py"))
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"skill_management": _skill_management_script}):
        spec.loader.exec_module(module)
    return module


class FakeSandbox:
    """实现 execute/upload/download 协议，执行可信入口并隔离远端根目录。"""

    def __init__(self, root):
        self.root = root
        self.runtime = load_runtime()
        self.runtime.ROOT = root
        self.calls = []
        self.fail_download = False
        self.tamper_manifest = None
        self.lose_response = None
        self.other_files = {}

    def transaction(self):
        return nullcontext()

    def upload_files(self, files):
        for path, content in files:
            if path.startswith("/tmp/myagent-skill-"):
                with zipfile.ZipFile(BytesIO(content)) as archive:
                    assert set(archive.namelist()) == {"skill_management.py", "sandbox_runtime.py"}
            elif path.startswith("/skills/"):
                destination = self.root / path.removeprefix("/skills/")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(content)
            else:
                self.other_files[path] = content
        return [SimpleNamespace(path=path, error=None) for path, _ in files]

    def execute(self, command, *, timeout=None):
        parts = shlex.split(command)
        if parts[0] == "rm":
            if parts[-1].startswith("/skills/"):
                (self.root / parts[-1].removeprefix("/skills/")).unlink(missing_ok=True)
            return SimpleNamespace(exit_code=0, output="")
        request = json.loads(parts[-1])
        self.calls.append(request)
        try:
            result = self.runtime.dispatch(request)
            if request["operation"] == self.lose_response:
                return SimpleNamespace(exit_code=0, output="truncated response")
            if self.tamper_manifest and "files" in result:
                self.tamper_manifest(result)
            return SimpleNamespace(exit_code=0, output=json.dumps({"result": result}))
        except Exception as error:
            return SimpleNamespace(exit_code=1, output=type(error).__name__)

    def download_files(self, paths):
        responses = []
        for path in paths:
            file = self.root / path.removeprefix("/skills/")
            content = (file.read_bytes() if file.is_file() else None) if path.startswith("/skills/") else self.other_files.get(path)
            error = "transfer failed" if self.fail_download else (None if content is not None else "file_not_found")
            responses.append(SimpleNamespace(path=path, error=error, content=content))
        return responses


class SandboxSkillTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.local = self.base / "local"
        self.remote = self.base / "remote"
        self.backend = FakeSandbox(self.remote)
        self.tools = _skill_management_script.create_skill_management_tools(
            self.local, {"worker"}, sandbox_backend=self.backend)

    def skill(self, root, relative="main/demo", description="example"):
        directory = root / relative
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "SKILL.md").write_text(
            f"---\nname: demo\ndescription: {description}\n---\n\nInstructions\n", encoding="utf-8")
        (directory / "code.py").write_text("raise RuntimeError('must never run on host')", encoding="utf-8")
        return directory

    def assign(self, target="worker"):
        return self.tools[1].invoke({"skill_name": "demo", "subagent_name": target})

    def test_agent_created_skill_is_allocated_and_persisted(self):
        self.skill(self.remote)
        self.assertTrue(json.loads(self.assign())["ok"])
        self.assertFalse((self.remote / "main/demo").exists())
        self.assertEqual((self.local / "subagents/worker/demo/code.py").read_bytes(),
                         (self.remote / "subagents/worker/demo/code.py").read_bytes())
        self.assertFalse((self.local / "main/demo").exists())

    def test_stale_second_user_assignment_keeps_latest_publication(self):
        self.skill(self.local, description="old")
        agents = self.base / "AGENTS.md"
        agents.write_text("instructions", encoding="utf-8")
        synchronizer = SandboxSkillSynchronizer(self.local, agents)
        second = FakeSandbox(self.base / "second")
        synchronizer.sync(self.backend)
        synchronizer.sync(second)
        self.skill(self.remote, description="new")
        self.assertTrue(json.loads(self.assign("main"))["ok"])
        second_tools = _skill_management_script.create_skill_management_tools(
            self.local,
            {"worker"},
            sandbox_backend=second,
            synchronize=lambda: synchronizer.sync(second),
        )
        result = second_tools[1].invoke({"skill_name": "demo", "subagent_name": "worker"})
        self.assertTrue(json.loads(result)["ok"], result)
        self.assertIn("description: new", (self.local / "subagents/worker/demo/SKILL.md").read_text())

    def test_trusted_runtime_imports_without_langchain(self):
        package = self.base / "runtime.zip"
        package.write_bytes(_runtime_package())
        code = (
            "import sys; sys.path.insert(0,sys.argv[1]); "
            "import sandbox_runtime; "
            "assert 'langchain_core.tools' not in sys.modules"
        )
        result = subprocess.run([sys.executable, "-I", "-c", code, str(package)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_async_tool_invocation_uses_sandbox(self):
        self.skill(self.remote)
        result = asyncio.run(self.tools[1].ainvoke({"skill_name": "demo", "subagent_name": "main"}))
        self.assertTrue(json.loads(result)["ok"])
        self.assertTrue((self.local / "main/demo/SKILL.md").is_file())
        self.assertEqual(self.backend.calls[0]["operation"], "assign")

    def test_main_assignment_and_query_use_remote_metadata(self):
        self.skill(self.remote, description="remote")
        self.assertTrue(json.loads(self.assign("main"))["ok"])
        self.skill(self.local, description="local")
        result = json.loads(self.tools[2].invoke({"subagent_name": "main"}))
        self.assertEqual(result["main"][0]["description"], "remote")
        self.assertNotIn(str(self.local), json.dumps(result))

    def test_list_refreshes_fixed_subagent_skills_in_sandbox(self):
        """列表查询应先同步本地固定技能，避免旧用户沙箱返回空列表。"""
        self.skill(
            self.local,
            "subagents/procurement_analyst/procurement-analysis",
            description="采购订单分析与报告",
        )
        skill_directory = self.local / "subagents/procurement_analyst/procurement-analysis"
        (skill_directory / "SKILL.md").write_text(
            "---\nname: procurement-analysis\ndescription: 采购订单分析与报告\n---\n",
            encoding="utf-8",
        )
        (skill_directory / "metadata.json").write_text(
            json.dumps(
                {"name": "procurement-analysis", "description": "采购订单分析与报告"},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        agents = self.base / "AGENTS.md"
        agents.write_text("instructions", encoding="utf-8")
        synchronizer = SandboxSkillSynchronizer(self.local, agents)
        tools = _skill_management_script.create_skill_management_tools(
            self.local,
            {"procurement_analyst", "procurement_order"},
            sandbox_backend=self.backend,
            synchronize=lambda: synchronizer.sync(self.backend),
        )

        result = json.loads(tools[2].invoke({"subagent_name": "procurement_analyst"}))

        self.assertEqual(
            result["procurement_analyst"],
            [{
                "skill_name": "procurement-analysis",
                "name": "procurement-analysis",
                "description": "采购订单分析与报告",
            }],
        )

    def test_download_failure_restores_remote_source(self):
        self.skill(self.remote)
        self.backend.fail_download = True
        self.assertIn("持久化失败", self.assign())
        self.assertTrue((self.remote / "main/demo/SKILL.md").exists())
        self.assertFalse((self.remote / "subagents/worker/demo").exists())

    def test_publish_failure_restores_both_versions(self):
        self.skill(self.remote, description="new")
        old = self.skill(self.local, "subagents/worker/demo", description="old")
        original = Path.replace

        def replace(path, target):
            if path.name == "new":
                raise OSError("disk full")
            return original(path, target)

        with patch.object(Path, "replace", replace):
            self.assertIn("持久化失败", self.assign())
        self.assertIn("old", (old / "SKILL.md").read_text())
        self.assertTrue((self.remote / "main/demo").exists())

    def test_lost_prepare_and_commit_responses_roll_back_both_copies(self):
        for operation in ("assign", "finish"):
            with self.subTest(operation=operation):
                self.skill(self.remote, description="new")
                self.skill(self.local, "subagents/worker/demo", description="old")
                self.backend.lose_response = operation
                self.assertIn("持久化失败", self.assign())
                self.assertTrue((self.remote / "main/demo").exists())
                self.assertFalse((self.remote / "subagents/worker/demo").exists())
                self.assertIn("old", (self.local / "subagents/worker/demo/SKILL.md").read_text())

    def test_failure_renaming_second_local_copy_restores_first(self):
        self.skill(self.remote)
        self.skill(self.local)
        self.skill(self.local, "subagents/worker/demo", description="old")
        original = Path.replace

        def replace(path, target):
            if path == self.local / "main/demo":
                raise OSError("locked")
            return original(path, target)

        with patch.object(Path, "replace", replace):
            self.assertIn("持久化失败", self.assign())
        self.assertTrue((self.local / "main/demo").exists())
        self.assertIn("old", (self.local / "subagents/worker/demo/SKILL.md").read_text())

    def test_rejects_malicious_and_oversized_export(self):
        for path in ("../escape", "/absolute", "C:/escape", "a\\b", "CON", "a/./b"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                _local_path(self.local, path)
        self.skill(self.remote)
        self.backend.tamper_manifest = lambda result: result["files"][0].update(size=MAX_BYTES + 1)
        self.assertIn("持久化失败", self.assign())
        self.assertFalse((self.local / "subagents/worker/demo").exists())

    def test_delete_removes_both_copies(self):
        self.skill(self.remote)
        self.assign()
        result = self.tools[3].invoke({"skill_name": "demo", "subagent_name": "worker"})
        self.assertTrue(json.loads(result)["ok"])
        self.assertFalse((self.remote / "subagents/worker/demo").exists())
        self.assertFalse((self.local / "subagents/worker/demo").exists())

    def test_delete_local_failure_restores_remote(self):
        self.skill(self.remote)
        self.assign()
        with patch.object(Path, "replace", side_effect=OSError("read only")):
            result = self.tools[3].invoke({"skill_name": "demo", "subagent_name": "worker"})
        self.assertIn("持久化失败", result)
        self.assertTrue((self.remote / "subagents/worker/demo").exists())
        self.assertTrue((self.local / "subagents/worker/demo").exists())

    def test_update_transfer_failure_restores_old_version(self):
        self.skill(self.remote, description="old")
        self.assign()
        archive_bytes = BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("SKILL.md", "---\nname: demo\ndescription: new\n---\n")
        self.backend.fail_download = True
        with patch.object(_skill_management_script.urllib.request, "urlopen", return_value=BytesIO(archive_bytes.getvalue())):
            result = self.tools[4].invoke({"skill_url": "https://example.com/demo.zip", "subagent_name": "worker"})
        self.assertIn("持久化失败", result)
        for root in (self.local, self.remote):
            self.assertIn("old", (root / "subagents/worker/demo/SKILL.md").read_text())

    def test_update_success_publishes_new_version_without_main_copy(self):
        self.skill(self.remote, description="old")
        self.assign()
        archive_bytes = BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("SKILL.md", "---\nname: demo\ndescription: new\n---\n")
        with patch.object(_skill_management_script.urllib.request, "urlopen", return_value=BytesIO(archive_bytes.getvalue())):
            result = self.tools[4].invoke({"skill_url": "https://example.com/demo.zip", "subagent_name": "worker"})
        self.assertTrue(json.loads(result)["ok"])
        for root in (self.local, self.remote):
            self.assertIn("new", (root / "subagents/worker/demo/SKILL.md").read_text())
            self.assertFalse((root / "main/demo").exists())

    def test_hash_mismatch_and_manifest_traversal_are_rejected(self):
        self.skill(self.remote)
        for change in ({"sha256": "wrong"}, {"path": "../escape"}):
            with self.subTest(change=change):
                self.backend.tamper_manifest = lambda result: result["files"][0].update(change)
                self.assertIn("持久化失败", self.assign())
                self.assertTrue((self.remote / "main/demo").exists())

    def test_remote_symlink_validation_without_windows_privilege(self):
        directory = self.skill(self.remote)
        original = Path.is_symlink

        def is_symlink(path):
            return path == directory / "code.py" or original(path)

        with patch.object(Path, "is_symlink", is_symlink):
            self.assertIn("失败", self.assign())
        self.assertFalse(self.local.exists())

    def test_protected_skill_is_rejected(self):
        for name in ("skill-management", "SKILL-MANAGEMENT"):
            result = self.tools[1].invoke({"skill_name": name, "subagent_name": "worker"})
            self.assertNotIn('"ok": true', result)
        self.assertEqual(self.backend.calls, [])

    def test_symlink_is_rejected_before_export(self):
        directory = self.skill(self.remote)
        try:
            (directory / "linked").symlink_to(directory / "code.py")
        except OSError:
            self.skipTest("Windows account cannot create symbolic links")
        self.assertIn("失败", self.assign())
        self.assertFalse(self.local.exists())

    def test_download_is_remote_only_and_quotes_external_input(self):
        archive_bytes = BytesIO()
        with zipfile.ZipFile(archive_bytes, "w") as archive:
            archive.writestr("SKILL.md", "---\nname: demo\ndescription: downloaded\n---\n")
        url = "https://example.com/demo.zip?unused=$(touch%20bad)'"
        with patch.object(_skill_management_script.urllib.request, "urlopen", return_value=BytesIO(archive_bytes.getvalue())):
            result = json.loads(self.tools[0].invoke({"skill_url": url}))
        self.assertEqual(result["skill_name"], "demo")
        self.assertEqual(self.backend.calls[0]["url"], url)
        self.assertTrue((self.remote / "main/demo").exists())
        self.assertFalse(self.local.exists())
