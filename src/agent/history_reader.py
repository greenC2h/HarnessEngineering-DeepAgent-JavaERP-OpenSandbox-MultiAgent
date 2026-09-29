"""从 LangGraph checkpoint 恢复会话展示消息。"""

from __future__ import annotations

from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import StateBackend
from langgraph._internal._constants import NS_END, NS_SEP
from langgraph.types import StateSnapshot

from agent.config import MAIN_MODEL


INTERRUPT_CHANNEL = "__interrupt__"


class ThreadHistoryReader:
    """
    通过只读状态图重放指定会话的消息增量。

    DeepAgents 的 ``messages`` 使用 ``DeltaChannel`` 保存增量，消息必须由图重建；
    待处理中断从当前 checkpoint 补全；旧版流取消造成父记录缺失时，补读活动子图。
    该模块将恢复细节
    封装为仅接受 ``thread_id`` 的接口；它只访问持久化数据库，不调用模型或沙箱。
    """

    def __init__(self, *, checkpointer: Any) -> None:
        """
        创建用于恢复状态的最小 DeepAgents 图。
        """
        # create_deep_agent 当前要求显式模型；本图只调用 aget_state()，不会执行模型。
        self._checkpointer = checkpointer
        self._state_graph = create_deep_agent(
            model=MAIN_MODEL,
            backend=StateBackend(),
            checkpointer=checkpointer,
        )

    async def get_messages(self, thread_id: str) -> list[Any]:
        """
        重放一个会话的 checkpoint，并返回完整消息序列。
        """
        state = await self.get_state(thread_id)
        return list(state.values.get("messages", []))

    async def get_state(self, thread_id: str) -> StateSnapshot:
        """
        恢复消息及待处理任务、中断，供历史展示和安全投递共同使用。
        """
        state = await self._state_graph.aget_state(
            {"configurable": {"thread_id": thread_id}}
        )
        # 最小读图没有主图的审批 middleware 节点，SDK 会跳过未知节点的任务。
        # 仅补读同一 checkpoint 的中断写入；messages 仍由图重建 DeltaChannel。
        if not state.config.get("configurable", {}).get("checkpoint_id"):
            return state
        saved = await self._checkpointer.aget_tuple(state.config)
        if saved is None:
            return state
        interrupts = {item.id: item for item in state.interrupts}
        for _, channel, values in saved.pending_writes or []:
            if channel == INTERRUPT_CHANNEL:
                for item in values:
                    interrupts[item.id] = item
        for task in state.tasks:
            if not task.error or task.interrupts:
                continue
            # 与 LangGraph _aprepare_state_snapshot 的子图 namespace 构造一致。
            # 只查询当前失败任务的子图，不扫描历史 namespace，避免恢复已完成的审批。
            parent_ns = state.config["configurable"].get("checkpoint_ns", "")
            task_ns = f"{task.name}{NS_END}{task.id}"
            if parent_ns:
                task_ns = f"{parent_ns}{NS_SEP}{task_ns}"
            child = await self._checkpointer.aget_tuple({"configurable": {
                "thread_id": thread_id, "checkpoint_ns": task_ns,
            }})
            if child is not None:
                for _, channel, values in child.pending_writes or []:
                    if channel == INTERRUPT_CHANNEL:
                        for item in values:
                            interrupts[item.id] = item
        return state._replace(interrupts=tuple(interrupts.values()))
