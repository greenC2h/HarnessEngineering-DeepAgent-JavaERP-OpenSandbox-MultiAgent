"""单个 OpenSandbox 实例的 DeepAgents 沙箱适配器。"""

from __future__ import annotations

import logging
from datetime import timedelta

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox
from opensandbox.exceptions import SandboxApiException
from opensandbox.models.execd import RunCommandOpts
from opensandbox.models.filesystem import WriteEntry
from opensandbox.sync import SandboxSync


class _ExpectedMissingManifestFilter(logging.Filter):
    """仅隐藏首次同步时 manifest 不存在所产生的 SDK 堆栈日志。"""

    def filter(self, record: logging.LogRecord) -> bool:
        return not (
            record.name == "opensandbox.sync.adapters.filesystem_adapter"
            and record.getMessage() == "Failed to read file /.myagent/skills-manifest.json"
        )


logging.getLogger("opensandbox.sync.adapters.filesystem_adapter").addFilter(
    _ExpectedMissingManifestFilter()
)


class OpenSandboxBackend(BaseSandbox):
    """通过 ``BaseSandbox`` 暴露 OpenSandbox 的执行和文件传输能力。

    ``BaseSandbox`` 会从这里实现的三个原语派生其余文件系统操作，因此模型
    永远不会直接拿到宿主机文件系统后端。
    """

    def __init__(self, sandbox: SandboxSync, default_timeout_seconds: int) -> None:
        self._sandbox = sandbox
        self._id = str(sandbox.id)
        self._default_timeout_seconds = default_timeout_seconds

    @property
    def id(self) -> str:
        """返回服务端分配的沙箱标识。"""
        return self._id

    def close(self) -> None:
        """
        释放 SDK 传输资源，但不终止远端持久化沙箱。
        """
        self._sandbox.close()

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        """执行一条 shell 命令，并保留合并输出和退出码。"""
        effective_timeout = self._default_timeout_seconds if timeout is None else timeout
        try:
            execution = self._sandbox.commands.run(
                command,
                opts=RunCommandOpts(timeout=timedelta(seconds=effective_timeout)),
            )
            output = str(execution)
            exit_code = getattr(execution, "exit_code", None)
            return ExecuteResponse(output=output, exit_code=exit_code)
        except Exception as error:  # SDK 暴露的传输异常类型不稳定，统一转换为失败响应。
            return ExecuteResponse(output=f"OpenSandbox execution failed: {error}", exit_code=1)

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """逐个上传文件，避免单个路径失败掩盖其他文件的结果。"""
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                # SDK 要求使用十进制权限数字，而不是 Unix 权限位掩码。
                self._sandbox.files.write_files([WriteEntry(path=path, data=content, mode=644)])
                responses.append(FileUploadResponse(path=path))
            except Exception as error:  # 不同服务端传输实现可能抛出不同异常类型。
                responses.append(FileUploadResponse(path=path, error=str(error)))
        return responses

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """下载指定文件，不把二进制内容错误转换成文本。"""
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                responses.append(FileDownloadResponse(path=path, content=self._sandbox.files.read_bytes(path)))
            except Exception as error:  # 不同服务端传输实现可能抛出不同异常类型。
                if isinstance(error, SandboxApiException) and error.status_code == 404:
                    failure = "file_not_found"
                elif isinstance(error, SandboxApiException) and error.status_code == 403:
                    failure = "permission_denied"
                else:
                    failure = f"download_failed: {error}"
                responses.append(FileDownloadResponse(path=path, error=failure))
        return responses

    def is_healthy(self) -> bool:
        """检查远端沙箱健康状态，不把 SDK 异常泄漏给调用方。"""
        try:
            return bool(self._sandbox.is_healthy())
        except Exception:
            return False
