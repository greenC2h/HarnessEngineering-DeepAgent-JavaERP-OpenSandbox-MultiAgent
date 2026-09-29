"""支持热替换的稳定沙箱后端引用。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import RLock

from deepagents.backends.protocol import ExecuteResponse, FileDownloadResponse, FileUploadResponse
from deepagents.backends.sandbox import BaseSandbox


class SandboxBackendProxy(BaseSandbox):
    """把所有 BaseSandbox 原语转发到当前用户沙箱。

    Agent 图在构建时会捕获后端对象。恢复沙箱时替换被代理的后端，而不是重建
    Agent 图，可以保持图中已有引用继续有效。
    """

    def __init__(self, backend: BaseSandbox | None = None) -> None:
        self._backend = backend
        self._lock = RLock()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """
        在多步骤同步期间固定后端；同步完成前不允许替换后端。
        """
        with self._lock:
            yield

    def _require_backend(self) -> BaseSandbox:
        """
        拒绝在已关闭或仅用于观察的代理上执行操作。
        """
        if self._backend is None:
            raise RuntimeError("Sandbox is unavailable outside an execution context")
        return self._backend

    @property
    def id(self) -> str:
        """返回当前沙箱标识。"""
        with self._lock:
            return self._require_backend().id

    def replace_backend(self, backend: BaseSandbox) -> None:
        """
        等待进行中的操作完成，安装新后端并关闭旧客户端。
        """
        with self._lock:
            previous = self._backend
            self._backend = backend
            if previous is not backend:
                close = getattr(previous, "close", None)
                if callable(close):
                    close()

    def close(self) -> None:
        """
        等待活动操作完成，并只关闭一次本地资源。
        """
        with self._lock:
            previous = self._backend
            self._backend = None
            close = getattr(previous, "close", None)
            if callable(close):
                close()

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        """将命令执行转发到当前沙箱。"""
        with self._lock:
            return self._require_backend().execute(command, timeout=timeout)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """将文件上传转发到当前沙箱。"""
        with self._lock:
            return self._require_backend().upload_files(files)

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """将文件下载转发到当前沙箱。"""
        with self._lock:
            return self._require_backend().download_files(paths)

    def is_healthy(self) -> bool:
        """使用当前后端的健康探针返回沙箱状态。"""
        with self._lock:
            if self._backend is None:
                return False
            probe = getattr(self._backend, "is_healthy", None)
            return bool(probe()) if callable(probe) else self.execute("true").exit_code == 0
