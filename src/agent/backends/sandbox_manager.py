"""按用户持久化管理 OpenSandbox 的生命周期。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from opensandbox.config.connection_sync import ConnectionConfigSync
from opensandbox.exceptions import SandboxApiException
from opensandbox.models.sandboxes import SandboxState
from opensandbox.sync import SandboxSync
from opensandbox.sync.manager import SandboxManagerSync

from agent.backends.open_sandbox import OpenSandboxBackend
from agent.backends.sandbox_proxy import SandboxBackendProxy
from agent.backends.skill_sync import SandboxSkillSynchronizer
from agent.config import (
    OPEN_SANDBOX_API_KEY,
    OPEN_SANDBOX_DEFAULT_TIMEOUT_SECONDS,
    OPEN_SANDBOX_HOST,
    OPEN_SANDBOX_IMAGE,
    OPEN_SANDBOX_PORT,
    OPEN_SANDBOX_PREWARM_ENABLED,
    OPEN_SANDBOX_SANDBOX_TIMEOUT_SECONDS,
    SKILLS_ROOT,
)


SANDBOX_NAMESPACE_PREFIX = ("sandboxes",)
logger = logging.getLogger(__name__)


class SandboxManager:
    """在单进程内管理按用户复用的客户端和一个未分配预热沙箱。"""

    def __init__(self, store: Any) -> None:
        self._store = store
        self._proxies: dict[str, SandboxBackendProxy] = {}
        self._user_locks: dict[str, asyncio.Lock] = {}
        self._warm_lock = asyncio.Lock()
        self._warm_reserve: OpenSandboxBackend | None = None
        self._warm_task: asyncio.Task[None] | None = None
        self._operations: set[asyncio.Task[SandboxBackendProxy]] = set()
        self._close_task: asyncio.Task[None] | None = None
        self._is_closed = False
        self._connection: ConnectionConfigSync | None = None
        if OPEN_SANDBOX_API_KEY:
            self._connection = ConnectionConfigSync(
                api_key=OPEN_SANDBOX_API_KEY,
                domain=f"{OPEN_SANDBOX_HOST}:{OPEN_SANDBOX_PORT}",
            )

    async def initialize(self) -> None:
        """
        安排一个已同步项目文件的预热沙箱，不让 SDK 操作阻塞服务启动。
        """
        if self._connection is None:
            # OpenSandbox 是可选执行环境；缺少凭据不应阻止只读页面和历史接口启动。
            logger.warning("未配置 OPEN_SANDBOX_API_KEY，已禁用沙箱预热和 Agent 执行")
            return
        async with self._warm_lock:
            self._ensure_open()
            self._schedule_prewarm_locked()

    def _ensure_open(self) -> None:
        if self._is_closed:
            raise RuntimeError("沙箱管理器已关闭")

    def _ensure_configured(self) -> None:
        """确认当前请求可创建或连接 OpenSandbox 实例。"""
        if self._connection is None:
            raise RuntimeError("未配置 OPEN_SANDBOX_API_KEY，无法创建 OpenSandbox 沙箱")

    def _schedule_prewarm_locked(self) -> None:
        """
        在预热锁保护预留沙箱所有权期间，合并重复的补充请求。
        """
        if (
            self._is_closed
            or not OPEN_SANDBOX_PREWARM_ENABLED
            or self._warm_reserve is not None
            or (self._warm_task is not None and not self._warm_task.done())
        ):
            return
        self._warm_task = asyncio.create_task(self._prewarm())

    async def _prewarm(self) -> None:
        """
        只有完整同步成功的预热沙箱才会发布；失败时回退到按需创建。
        """
        backend = None
        try:
            backend = await self._run_sync(
                self._create_reserve, cleanup=self._discard_reserve,
            )
            async with self._warm_lock:
                if not self._is_closed:
                    self._warm_reserve = backend
                    backend = None
        except Exception as error:
            # SDK 异常文本可能包含凭据或响应体，只记录异常类型，避免泄密。
            logger.warning("沙箱预热失败，将按需创建 (%s)", type(error).__name__)
        finally:
            if backend is not None:
                await self._run_sync(self._discard_reserve, backend)

    async def get_backend(self, user_id: str) -> SandboxBackendProxy:
        """
        返回并续期用户的稳定代理；关闭时等待所有已接纳请求完成。
        """
        self._ensure_open()
        self._ensure_configured()
        task = asyncio.create_task(self._get_backend(user_id))
        self._operations.add(task)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            task.cancel()
            try:
                await self._settle(task)
            except (Exception, asyncio.CancelledError):
                pass
            raise
        finally:
            self._operations.discard(task)

    async def _get_backend(self, user_id: str) -> SandboxBackendProxy:
        """
        只串行化当前用户的数据库绑定、恢复和代理替换，不阻塞其他用户。
        """
        async with self._user_locks.setdefault(user_id, asyncio.Lock()):
            self._ensure_open()
            proxy = self._proxies.get(user_id)
            if proxy is not None and await self._run_sync(proxy.is_healthy):
                await self._run_sync(self._renew_on_access, proxy.id)
                return proxy

            backend, sandbox_id = await self._resolve_backend(user_id)
            try:
                await self._run_sync(self._renew_on_access, sandbox_id)
                await self._store.aput(
                    (*SANDBOX_NAMESPACE_PREFIX, user_id),
                    "current",
                    {"sandbox_id": sandbox_id},
                    index=False,
                )
            except BaseException:
                # 数据库写入可能已在异常/取消前提交。此时不能把已分配客户端
                # 放回预热池，也不能删除它对应的远端实例。
                await self._run_sync(backend.close)
                raise
            if proxy is None:
                proxy = SandboxBackendProxy(backend)
                self._proxies[user_id] = proxy
            else:
                await self._run_sync(proxy.replace_backend, backend)
            return proxy

    async def close(self) -> None:
        """
        停止接纳新请求，排空工作任务，只删除预热池实例并关闭用户客户端。
        """
        if self._close_task is None:
            self._is_closed = True
            self._close_task = asyncio.create_task(self._close())
        try:
            await asyncio.shield(self._close_task)
        except asyncio.CancelledError:
            # 调用方取消不能让生命周期管理器在工作任务仍可能写入绑定时关闭，
            # 也不能遗弃由工作线程持有的 SDK 客户端。
            await self._settle(self._close_task)
            raise

    async def _close(self) -> None:
        """
        释放共享生命周期资源前，完成所有已接纳的操作。
        """
        await asyncio.gather(*self._operations, return_exceptions=True)
        if self._warm_task is not None:
            await asyncio.gather(self._warm_task, return_exceptions=True)
        async with self._warm_lock:
            reserve, self._warm_reserve = self._warm_reserve, None
        proxies = list(self._proxies.values())
        self._proxies.clear()
        self._user_locks.clear()
        cleanup = [asyncio.to_thread(proxy.close) for proxy in proxies]
        if reserve is not None:
            cleanup.append(asyncio.to_thread(self._discard_reserve, reserve))
        results = await asyncio.gather(*cleanup, return_exceptions=True)
        for result in results:
            if isinstance(result, BaseException):
                raise result

    async def _resolve_backend(self, user_id: str) -> tuple[OpenSandboxBackend, str]:
        """
        持久化 ID 优先；只有确认实例不存在、已终止或已失败时，才允许领取预热沙箱。
        """
        item = await self._store.aget((*SANDBOX_NAMESPACE_PREFIX, user_id), "current")
        sandbox_id = str(item.value.get("sandbox_id") or "") if item is not None else ""
        if sandbox_id and not await self._run_sync(self._is_confirmed_gone, sandbox_id):
            backend = await self._run_sync(
                self._connect_existing, sandbox_id, cleanup=lambda value: value.close(),
            )
            return backend, sandbox_id
        async with self._warm_lock:
            self._ensure_open()
            backend, self._warm_reserve = self._warm_reserve, None
            if backend is not None:
                # 原子摘除预热实例：就绪检查在锁外执行时，其他用户也不能领取它。
                self._schedule_prewarm_locked()
        if backend is not None:
            try:
                is_healthy = await self._run_sync(backend.is_healthy)
            except BaseException:
                # 实例仍未分配：此时尚未写数据库，也没有用户操作开始使用它。
                await self._run_sync(self._discard_reserve, backend)
                raise
            if not is_healthy:
                # 空闲预热实例可能已过期；它尚未拥有用户数据，可以直接丢弃。
                await self._run_sync(self._discard_reserve, backend)
                backend = None
        if backend is None:
            backend = await self._run_sync(
                self._create_backend, user_id, cleanup=lambda value: value.close(),
            )
        return backend, backend.id

    @staticmethod
    async def _settle(task: asyncio.Task[Any]) -> Any:
        """
        即使等待方反复被取消，也要排空当前任务并收回其所有权。
        """
        while not task.done():
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                continue
        return task.result()

    async def _run_sync(
        self, function: Callable[..., Any], *args: Any,
        cleanup: Callable[[Any], None] | None = None,
    ) -> Any:
        """
        保留不可取消线程及其最终返回值的所有权，避免资源泄漏。
        """
        task = asyncio.create_task(asyncio.to_thread(function, *args))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                value = await self._settle(task)
                if cleanup is not None:
                    await self._settle(asyncio.create_task(asyncio.to_thread(cleanup, value)))
            except Exception as error:
                logger.warning("取消后沙箱资源回收失败 (%s)", type(error).__name__)
            raise

    def _connect_existing(self, sandbox_id: str) -> OpenSandboxBackend:
        """
        重新连接时，不把健康检查或传输错误误判为工作区丢失。
        """
        sandbox = SandboxSync.connect(sandbox_id, connection_config=self._connection)
        try:
            backend = OpenSandboxBackend(sandbox, OPEN_SANDBOX_DEFAULT_TIMEOUT_SECONDS)
            if backend.is_healthy():
                return backend
            raise RuntimeError("用户沙箱暂时不可用，请稍后重试；原沙箱及持久化标识已保留")
        except BaseException:
            sandbox.close()
            raise

    def _create_backend(self, user_id: str | None = None) -> OpenSandboxBackend:
        """
        创建客户端；预热实例故意不写入用户元数据。
        """
        sandbox = SandboxSync.create(
            image=OPEN_SANDBOX_IMAGE,
            timeout=timedelta(seconds=OPEN_SANDBOX_SANDBOX_TIMEOUT_SECONDS),
            metadata={"myagent_user_id": user_id} if user_id is not None else {},
            connection_config=self._connection,
        )
        try:
            backend = OpenSandboxBackend(sandbox, OPEN_SANDBOX_DEFAULT_TIMEOUT_SECONDS)
        except BaseException:
            sandbox.close()
            raise
        return backend

    def _create_reserve(self) -> OpenSandboxBackend:
        """
        在暴露未分配实例前，先同步项目技能和 Agent 指令。
        """
        backend = self._create_backend()
        try:
            SandboxSkillSynchronizer(
                SKILLS_ROOT, Path(__file__).resolve().parents[1] / "memory" / "AGENTS.md",
            ).sync(SandboxBackendProxy(backend))
        except BaseException:
            self._discard_reserve(backend)
            raise
        return backend

    def _discard_reserve(self, backend: OpenSandboxBackend) -> None:
        """
        只终止本地创建且从未分配给用户的预热实例，然后关闭其客户端。
        """
        try:
            manager = SandboxManagerSync.create(connection_config=self._connection)
            try:
                try:
                    manager.kill_sandbox(backend.id)
                except SandboxApiException as error:
                    # 空闲预热实例可能已经因过期被服务端删除。
                    if error.status_code != 404:
                        raise
            finally:
                manager.close()
        finally:
            backend.close()

    def _renew_on_access(self, sandbox_id: str) -> None:
        """
        访问时延长过期时间；续期失败不能成为替换用户沙箱的理由。
        """
        try:
            manager = SandboxManagerSync.create(connection_config=self._connection)
            try:
                manager.renew_sandbox(
                    sandbox_id, timedelta(seconds=OPEN_SANDBOX_SANDBOX_TIMEOUT_SECONDS),
                )
            finally:
                manager.close()
        except Exception as error:
            logger.warning("沙箱续期失败，保留现有沙箱及标识 (%s)", type(error).__name__)

    def _is_confirmed_gone(self, sandbox_id: str) -> bool:
        """
        判断持久化沙箱是否已经不能继续使用。

        生命周期为 ``FAILED`` 的实例虽然仍可能被 API 查询到，但其执行环境
        已不可恢复；必须和 ``TERMINATED`` 一样触发新沙箱分配，否则用户会
        持续连接同一个失效实例并最终超时。
        """
        manager = SandboxManagerSync.create(connection_config=self._connection)
        try:
            try:
                info = manager.get_sandbox_info(sandbox_id)
            except SandboxApiException as error:
                # 只有生命周期资源查询返回 404 才能确认不存在；execd/health 的
                # 404、超时或 503 都不能证明用户工作区已经丢失。
                if error.status_code == 404:
                    return True
                raise
            return info.status.state in {
                SandboxState.TERMINATED,
                SandboxState.FAILED,
            }
        finally:
            manager.close()
