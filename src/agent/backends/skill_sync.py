"""将项目维护的技能增量镜像到用户沙箱。"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
from pathlib import Path
from threading import RLock

from agent.backends.sandbox_proxy import SandboxBackendProxy


SANDBOX_SKILLS_ROOT = "/skills"
SANDBOX_MANIFEST_PATH = "/.myagent/skills-manifest.json"
SKILL_PERSISTENCE_LOCK = RLock()


class SandboxSkillSynchronizer:
    """以本地技能目录为权威来源，同时让 Agent 只读取沙箱副本。"""

    def __init__(self, skills_root: Path, agents_file: Path) -> None:
        self._skills_root = skills_root
        self._agents_file = agents_file

    def sync(self, backend: SandboxBackendProxy) -> bool:
        """只上传变更文件，并删除本地源中已经不存在的文件。

        manifest 保存在每个用户自己的沙箱中，因此开发者的修改会在该用户
        下次运行前被检测到，不依赖宿主机 mtime 或进程内缓存。
        """
        # 同步和技能管理共用同一把锁，避免开发者修改与生成技能回写并发交错。
        with SKILL_PERSISTENCE_LOCK, backend.transaction():
            return self._sync_locked(backend)

    def _sync_locked(self, backend: SandboxBackendProxy) -> bool:
        """
        所有文件变更成功后，最后才提交 manifest。
        """
        files = self._local_files()
        manifest = {path: self._hash(content) for path, content in files.items()}
        previous = self._read_manifest(backend)
        changed = [path for path, digest in manifest.items() if previous.get(path) != digest]
        removed = sorted(set(previous) - set(manifest))
        if not changed and not removed:
            return False

        uploads = [(path, files[path]) for path in changed]
        if uploads:
            self._upload_checked(backend, uploads)
        for path in removed:
            result = backend.execute(f"rm -f -- {shlex.quote(path)}")
            if result.exit_code != 0:
                raise RuntimeError(f"无法删除沙箱中的旧技能文件: {path}")
        # manifest 是本次同步的提交标记，必须最后写入，避免失败时留下错误索引。
        self._upload_checked(backend, [
            (SANDBOX_MANIFEST_PATH, json.dumps(manifest, sort_keys=True).encode("utf-8")),
        ])
        return True

    @staticmethod
    def _upload_checked(backend: SandboxBackendProxy, files: list[tuple[str, bytes]]) -> None:
        """
        要求每个上传文件都收到且仅收到成功确认。
        """
        responses = backend.upload_files(files)
        if (
            len(responses) != len(files)
            or sorted(response.path for response in responses) != sorted(path for path, _ in files)
            or any(response.error for response in responses)
        ):
            raise RuntimeError("技能同步失败：上传响应缺失、不匹配或包含错误")

    def _local_files(self) -> dict[str, bytes]:
        """
        只读取项目文件，并拒绝链接和越过配置根目录的路径。
        """
        root = self._skills_root.resolve()
        self._validate_local_path(self._skills_root, root)
        files: dict[str, bytes] = {"/AGENTS.md": self._agents_file.read_bytes()}
        # 先裁剪目录再继续遍历，防止 Windows 目录联接绕过 followlinks=False。
        for directory, directories, filenames in os.walk(self._skills_root, followlinks=False):
            parent = Path(directory)
            self._validate_local_path(parent, root)
            for name in directories:
                self._validate_local_path(parent / name, root)
            directories[:] = [name for name in directories if name != "__pycache__"]
            for name in filenames:
                path = parent / name
                self._validate_local_path(path, root)
                if path.suffix == ".pyc" or not path.is_file():
                    continue
                relative = path.relative_to(self._skills_root).as_posix()
                files[f"{SANDBOX_SKILLS_ROOT}/{relative}"] = path.read_bytes()
        return files

    @staticmethod
    def _validate_local_path(path: Path, root: Path) -> None:
        """
        拒绝符号链接、目录联接和解析后越出技能根目录的路径。
        """
        if path.is_symlink() or path.is_junction() or not path.resolve().is_relative_to(root):
            raise ValueError("技能目录包含符号链接、目录联接或越界路径，已停止同步")

    @staticmethod
    def _hash(content: bytes) -> str:
        return hashlib.sha256(content).hexdigest()

    @staticmethod
    def _read_manifest(backend: SandboxBackendProxy) -> dict[str, str]:
        """
        只有确认文件不存在才视为首次同步；读取失败时保留旧追踪状态。
        """
        responses = backend.download_files([SANDBOX_MANIFEST_PATH])
        if len(responses) != 1 or responses[0].path != SANDBOX_MANIFEST_PATH:
            raise RuntimeError("技能清单下载响应无效")
        response = responses[0]
        if response.error == "file_not_found":
            return {}
        if response.error or response.content is None:
            raise RuntimeError("技能清单读取失败，已停止同步以保留旧文件记录")
        try:
            value = json.loads(response.content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeError("技能清单格式损坏，已停止同步") from error
        if not isinstance(value, dict):
            raise RuntimeError("技能清单必须是 JSON 对象，已停止同步")
        for path, digest in value.items():
            # 沙箱内容不可信：禁止目录穿越，也禁止指向其他宿主机根路径。
            parts = path.split("/")
            is_skill_file = path.startswith(f"{SANDBOX_SKILLS_ROOT}/") and all(
                part not in {"", ".", ".."} for part in parts[2:]
            )
            if (
                (path != "/AGENTS.md" and not is_skill_file)
                or "\x00" in path
                or "\\" in path
                or not isinstance(digest, str)
            ):
                raise RuntimeError("技能清单包含非法路径或摘要")
        return value
