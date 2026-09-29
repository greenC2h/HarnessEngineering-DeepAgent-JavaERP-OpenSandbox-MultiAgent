"""采购 Agent 的加载、用户分组和会话配置管理。

本模块有两层状态：

* ``_user_groups`` 是当前 Python 服务进程的内存缓存，键为 ``user_id``。
  同一用户在当前进程内只创建一个 Agent，减少重复构建图和后端的开销。
* 每个用户分组中的 ``thread_ids`` 是该用户使用过的会话 ID 集合。
  调用 Agent 时传入的 ``thread_id`` 会由 PostgreSQL checkpointer 用来区分会话，
  因此同一用户可以同时拥有多个彼此独立的对话。

``thread_id`` 是业务会话 ID，不是操作系统进程 ID。
会话写操作的互斥仅在单个服务进程内有效，当前只支持单 worker 部署。
PostgreSQL 提供跨重启持久化；多 worker 部署前必须增加分布式协调。
用户身份仍是演示客户端声明的 user_id；归属校验不替代登录认证。
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Awaitable, Callable

from fastapi import HTTPException
from langchain_core.messages import AIMessage

from agent.config import close_async_persistence, create_async_persistence
from agent.backends.sandbox_manager import SandboxManager
from agent.history_reader import ThreadHistoryReader
from agent.schema import AsyncTaskBinding, ProcurementContext, UserGroup


AgentFactory = Callable[..., Awaitable[Any]]
SESSION_NAMESPACE_PREFIX = ("sessions",)
ASYNC_TASK_NAMESPACE_PREFIX = ("async_tasks",)
ANALYSIS_REPORT_NAMESPACE_PREFIX = ("analysis_reports",)
ASYNC_TASK_MESSAGE_PREFIX = "async-task-result:"


class AgentLoader:
    """管理 Agent 生命周期，并按用户复用当前进程中的 Agent 实例。

    分组关系为 ``user_id -> UserGroup(agent, thread_ids)``：

    * 不同 ``user_id`` 会进入不同的 ``UserGroup``，分别构造 Agent。
      主 Agent 又会将 memories 路由到以 ``user_id`` 为命名空间的 PostgreSQL Store，
      因此用户之间不能读取对方的记忆。
    * 同一 ``user_id`` 的不同 ``thread_id`` 共用该用户的 Agent，
      但每次调用都会把当前 ``thread_id`` 放入 LangGraph 配置。
      PostgreSQL checkpointer 因而将每个会话的消息和执行状态分别保存、分别恢复。

    PostgreSQL 负责跨进程、跨重启的持久化；本类只保存当前 Python 进程的缓存，不能作为多进程共享状态使用。
    """

    def __init__(self) -> None:
        # 仅当前 Python 进程可见。键为 user_id，值同时保存该用户唯一的
        # Agent 实例和所有已访问过的业务会话 thread_id。
        self._user_groups: dict[str, UserGroup] = {}
        self._lock = asyncio.Lock()
        self._user_locks: dict[str, asyncio.Lock] = {}
        self._active_threads: set[str] = set()
        self._initialized = False
        self._agent_factory: AgentFactory | None = None
        self._store: Any | None = None
        self._checkpointer: Any | None = None
        self._history_reader: ThreadHistoryReader | None = None
        self._sandbox_manager: SandboxManager | None = None

    async def initialize(self) -> None:
        """
        初始化持久化资源和 Agent 工厂，并在后台调度沙箱预热。
        """
        async with self._lock:
            if self._initialized:
                return
            from agent.main_agent import create_main_agent

            store, checkpointer = await create_async_persistence()
            manager = None
            try:
                manager = SandboxManager(store)
                await manager.initialize()
                reader = ThreadHistoryReader(checkpointer=checkpointer)
            except BaseException:
                # 构图失败或初始化取消时，不把半初始化资源暴露给其他请求。
                try:
                    if manager is not None:
                        await manager.close()
                finally:
                    await close_async_persistence(store, checkpointer)
                raise
            self._store, self._checkpointer = store, checkpointer
            self._sandbox_manager = manager
            self._agent_factory = create_main_agent
            self._history_reader = reader
            self._initialized = True

    @asynccontextmanager
    async def thread_operation(
        self, thread_id: str, *, defer: bool = False,
    ) -> AsyncIterator[bool]:
        """
        协调单进程内的会话写入；冲突时拒绝请求或让异步投递稍后重试。
        """
        # 检查和登记之间没有 await，同一事件循环内不会让两个操作同时进入。
        if thread_id in self._active_threads:
            if defer:
                yield False
                return
            raise HTTPException(status_code=409, detail="会话正在处理中，请稍后重试")
        self._active_threads.add(thread_id)
        try:
            yield True
        finally:
            self._active_threads.discard(thread_id)

    async def require_session(self, user_id: str, thread_id: str) -> None:
        """
        在访问已指定的会话前检查归属；修改者必须在会话 guard 内再次检查。
        """
        if await self.get_session(user_id, thread_id) is None:
            raise HTTPException(status_code=404, detail="会话不存在或无权访问")

    def create_config(
        self,
        thread_id: str | None = None,
        user_id: str | None = None,
        username: str | None = None,
    ) -> dict[str, dict[str, str]]:
        """
        创建一次 Agent 调用所需的身份和会话配置。

        ``user_id`` 决定用户身份及 memories 命名空间；
        ``thread_id`` 决定 checkpoint 使用哪个独立会话。
        未提供 ``thread_id`` 时创建新会话; 已提供时会继续该会话的 PostgreSQL checkpoint。
        """
        resolved_user_id = user_id or "anonymous"
        return {
            "configurable": {
                "thread_id": thread_id or str(uuid.uuid4()),
                "user_id": resolved_user_id,
                "username": username or resolved_user_id,
            }
        }

    async def get_agent_for_user(
        self,
        user_id: str,
        username: str,
        thread_id: str,
    ) -> Any:
        """
        获取用户 Agent，并登记该用户访问过的会话。

        例如，``u1`` 先后访问 ``order-a`` 和 ``order-b`` 时，
        内存结构为 ``{"u1": UserGroup(agent=..., thread_ids={"order-a", "order-b"})}``。
        两次调用取得同一个 Agent，但携带不同 ``thread_id``，所以不会混用两个会话的 checkpoint。
        """
        await self.initialize()
        assert self._agent_factory is not None
        assert self._store is not None
        assert self._checkpointer is not None
        assert self._sandbox_manager is not None

        # 用户级锁防止重复构建；沙箱探测和构图不会阻塞其他用户。
        async with self._user_locks.setdefault(user_id, asyncio.Lock()):
            group = self._user_groups.get(user_id)
            if group is None:
                group = UserGroup(username=username)
                self._user_groups[user_id] = group
            else:
                group.username = username
            group.thread_ids.add(thread_id)

            # 每次请求都探测已持久化的沙箱；管理器会对失效实例创建替代品，
            # 并通过稳定代理让已缓存的 Agent 自动使用新后端。
            sandbox_backend = await self._sandbox_manager.get_backend(user_id)

            if group.agent is None:
                group.agent = await self._agent_factory(
                    self.create_config(
                        thread_id=thread_id,
                        user_id=user_id,
                        username=username,
                    ),
                    store=self._store,
                    checkpointer=self._checkpointer,
                    sandbox_backend=sandbox_backend,
                )
            return group.agent

    async def shutdown(self) -> None:
        """
        释放当前进程内的 Agent 缓存和数据库连接。

        此操作不会删除 PostgreSQL 中任何 checkpoint 或 memories；
        服务下次启动后仍可使用相同的 user_id 和 thread_id 恢复持久化会话。
        """
        async with self._lock:
            self._user_groups.clear()
            self._agent_factory = None
            self._initialized = False
            store = self._store
            checkpointer = self._checkpointer
            self._store = None
            self._checkpointer = None
            self._history_reader = None
            manager = self._sandbox_manager
            self._sandbox_manager = None
            self._user_locks.clear()
            try:
                if manager is not None:
                    await manager.close()
            finally:
                if store is not None and checkpointer is not None:
                    await close_async_persistence(store, checkpointer)

    async def save_session(self, user_id: str, thread_id: str, title: str) -> None:
        """
        将用户会话索引保存到 PostgreSQL 的 LangGraph Store。

        Store 使用 ``("sessions", user_id)`` 作为命名空间、``thread_id`` 作为 key，value 保存标题和创建/更新时间；
        完整对话消息仍由 PostgreSQL Checkpointer 保存，本方法只维护侧边栏所需的索引数据。
        """
        await self.initialize()
        assert self._store is not None

        # Store 是现有 AsyncPostgresStore 的持久化入口，不写本地文件或内存缓存。
        namespace = (*SESSION_NAMESPACE_PREFIX, user_id)
        existing = await self._store.aget(namespace, thread_id)
        now = datetime.now(timezone.utc).isoformat()
        value = dict(existing.value) if existing is not None else {}
        existing_title = value.get("title")
        value.update(
            {
                "thread_id": thread_id,
                # 空会话先使用“新对话”。首条用户消息到达后仅更新这一次，
                # 后续轮次保留标题，避免侧边栏中会话名称持续跳变。
                "title": title if not existing_title or existing_title == "新对话" else existing_title,
                "created_at": value.get("created_at") or now,
                "updated_at": now,
            }
        )
        # title 只在首次创建时固定，后续消息只更新时间，避免侧边栏标题跳变。
        await self._store.aput(namespace, thread_id, value, index=False)

    async def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        """
        读取当前用户已登记的会话索引，并按更新时间倒序返回。
        """
        await self.initialize()
        assert self._store is not None
        items = await self._store.asearch(
            (*SESSION_NAMESPACE_PREFIX, user_id),
            limit=1_000,
        )
        sessions = [dict(item.value) for item in items]
        return sorted(sessions, key=lambda session: session.get("updated_at", ""), reverse=True)

    async def get_session(self, user_id: str, thread_id: str) -> dict[str, Any] | None:
        """
        读取当前用户的一条会话索引，用于常量时间的会话所有权校验。
        """
        await self.initialize()
        assert self._store is not None
        # 直接按命名空间和键读取，避免消息恢复或删除前扫描整个侧边栏列表。
        item = await self._store.aget((*SESSION_NAMESPACE_PREFIX, user_id), thread_id)
        return dict(item.value) if item is not None else None

    async def get_thread_messages(self, thread_id: str) -> list[Any]:
        """
        恢复指定线程的 LangGraph 消息状态。
        """
        await self.initialize()
        assert self._history_reader is not None
        return await self._history_reader.get_messages(thread_id)

    async def bind_async_task(
        self,
        task_id: str,
        *,
        user_id: str,
        username: str,
        thread_id: str,
    ) -> None:
        """持久化远程任务与主会话的归属关系。"""
        await self.initialize()
        assert self._store is not None
        await self._store.aput(
            ASYNC_TASK_NAMESPACE_PREFIX,
            task_id,
            {
                "task_id": task_id,
                "user_id": user_id,
                "username": username,
                "thread_id": thread_id,
            },
            index=False,
        )

    async def get_thread_state(self, thread_id: str) -> Any:
        """
        恢复包含待处理节点和中断的会话快照。
        """
        await self.initialize()
        assert self._history_reader is not None
        return await self._history_reader.get_state(thread_id)

    async def get_async_task_binding(self, task_id: str) -> AsyncTaskBinding | None:
        """读取远程任务绑定；旧任务未登记时返回空值。"""
        await self.initialize()
        assert self._store is not None
        item = await self._store.aget(ASYNC_TASK_NAMESPACE_PREFIX, task_id)
        if item is None:
            return None
        value = item.value
        return AsyncTaskBinding(
            task_id=task_id,
            user_id=str(value["user_id"]),
            username=str(value["username"]),
            thread_id=str(value["thread_id"]),
        )

    async def register_sandbox_report(self, task_id: str, report_path: str) -> dict[str, str] | None:
        """登记异步任务生成的沙箱报告元数据，不复制报告内容到项目存储。"""
        binding = await self.get_async_task_binding(task_id)
        if binding is None:
            return None

        # 同一任务重复轮询必须复用同一个报告入口，避免产生无效的元数据记录。
        report_id = uuid.uuid5(uuid.NAMESPACE_URL, f"analysis-report:{task_id}:{report_path}").hex
        await self.initialize()
        assert self._store is not None
        await self._store.aput(
            ANALYSIS_REPORT_NAMESPACE_PREFIX,
            report_id,
            {
                "user_id": binding.user_id,
                "report_path": report_path,
                "filename": report_path.rsplit("/", 1)[-1],
            },
            index=False,
        )
        return {"report_id": report_id, "label": "下载采购分析报告"}

    async def download_sandbox_report(self, user_id: str, report_id: str) -> tuple[str, bytes] | None:
        """按用户归属从其沙箱流式读取报告；报告正文不会落到项目本地。"""
        await self.initialize()
        assert self._store is not None
        assert self._sandbox_manager is not None
        item = await self._store.aget(ANALYSIS_REPORT_NAMESPACE_PREFIX, report_id)
        if item is None:
            return None
        metadata = item.value
        if metadata.get("user_id") != user_id:
            return None

        backend = await self._sandbox_manager.get_backend(user_id)
        report_path = str(metadata.get("report_path", ""))
        response = (await asyncio.to_thread(backend.download_files, [report_path]))[0]
        # 空文件不是有效报告；返回空值让 API 给出明确的 404，而不是下载一个空附件。
        if response.error or not response.content:
            return None
        return str(metadata.get("filename") or "procurement-analysis.md"), bytes(response.content)

    async def publish_async_task_result(
        self,
        task_id: str,
        *,
        content: str,
        artifact: dict[str, str] | None,
        report: dict[str, str] | None = None,
    ) -> bool:
        """将终态异步任务结果作为主 Agent 消息幂等写入主会话。"""
        binding = await self.get_async_task_binding(task_id)
        if binding is None:
            return False

        async with self.thread_operation(binding.thread_id, defer=True) as acquired:
            if not acquired or await self.get_session(binding.user_id, binding.thread_id) is None:
                return False
            return await self._publish_bound_result(
                binding,
                content=content,
                artifact=artifact,
                report=report,
            )

    async def _publish_bound_result(
        self,
        binding: AsyncTaskBinding,
        *,
        content: str,
        artifact: dict[str, str] | None,
        report: dict[str, str] | None,
    ) -> bool:
        """在持有会话 guard 后检查幂等性和暂停状态，再写入结果。"""
        task_id = binding.task_id
        message_id = f"{ASYNC_TASK_MESSAGE_PREFIX}{task_id}"
        # 必须经已编译图读取 DeltaChannel 状态，不能直接读取原始 checkpoint。
        state = await self.get_thread_state(binding.thread_id)
        messages = state.values.get("messages", [])
        message_ids = (
            message.get("id", "") if isinstance(message, dict) else getattr(message, "id", "")
            for message in messages
        )
        if message_id in message_ids:
            return True
        # aupdate_state 会改变 checkpoint 的后续调度，不能覆盖暂停中的工具执行。
        if state.next or state.interrupts:
            return False

        agent = await self.get_agent_for_user(
            user_id=binding.user_id,
            username=binding.username,
            thread_id=binding.thread_id,
        )
        content_blocks: list[dict[str, str]] = [
            {"type": "text", "text": content},
        ]
        if artifact is not None:
            content_blocks.append(artifact)
        if report is not None:
            content_blocks.append({"type": "sandbox_report", **report})

        # 使用固定消息 ID 配合 messages reducer，避免多次轮询或重试产生重复消息。
        await agent.aupdate_state(
            self.create_config(
                thread_id=binding.thread_id,
                user_id=binding.user_id,
                username=binding.username,
            ),
            {
                "messages": [
                    AIMessage(
                        id=message_id,
                        content=content_blocks,
                        additional_kwargs={"source": "main", "async_task_id": task_id},
                    )
                ]
            },
        )
        await self.save_session(binding.user_id, binding.thread_id, "新对话")
        return True

    async def delete_session(self, user_id: str, thread_id: str) -> bool:
        """
        删除用户会话的 checkpoint 数据和会话索引。
        """
        async with self.thread_operation(thread_id):
            await self.require_session(user_id, thread_id)
            return await self._delete_session(user_id, thread_id)

    async def _delete_session(self, user_id: str, thread_id: str) -> bool:
        """
        在持有会话 guard 时删除正文与索引，阻止延迟结果重建已删除会话。
        """
        await self.initialize()
        assert self._store is not None
        assert self._checkpointer is not None
        # 先删除正文 checkpoint，再删除索引，避免侧边栏指向不存在的会话。
        await self._checkpointer.adelete_thread(thread_id)
        await self._store.adelete((*SESSION_NAMESPACE_PREFIX, user_id), thread_id)
        group = self._user_groups.get(user_id)
        if group is not None:
            group.thread_ids.discard(thread_id)
        return True


agent_loader = AgentLoader()
