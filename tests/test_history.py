"""会话历史接口的回归测试。"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Command, interrupt

from agent.history_reader import ThreadHistoryReader
from api.history import get_session_messages, list_sessions, serialize_messages


class HistorySessionTests(unittest.IsolatedAsyncioTestCase):
    """确保空会话和已有会话都能通过侧边栏接口返回。"""

    async def test_list_sessions_includes_empty_new_session(self) -> None:
        """
        新会话还没有 checkpoint 消息时，列表接口仍应返回它。
        """
        indexed_session = {
            "thread_id": "new-thread",
            "title": "新对话",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        with (
            patch("api.history.agent_loader.list_sessions", new=AsyncMock(return_value=[indexed_session])),
            patch("api.history.agent_loader.get_thread_messages", new=AsyncMock(return_value=[])),
        ):
            response = await list_sessions(user_id="u1")

        self.assertEqual(response.sessions[0].thread_id, "new-thread")
        self.assertEqual(response.sessions[0].title, "新对话")
        self.assertEqual(response.sessions[0].message_count, 0)

    async def test_get_session_messages_returns_framework_state_messages(self) -> None:
        """
        历史接口应序列化 DeepAgents 重建出的 messages 状态。
        """
        with (
            patch("api.history.agent_loader.get_session", new=AsyncMock(return_value={"thread_id": "thread-1"})),
            patch(
                "api.history.agent_loader.get_thread_state",
                new=AsyncMock(return_value=SimpleNamespace(
                    values={"messages": [HumanMessage(content="查询采购订单"), AIMessage(content="已找到订单")]},
                    interrupts=(),
                )),
            ),
        ):
            response = await get_session_messages(thread_id="thread-1", user_id="u1")

        self.assertEqual(response.messages[0].content, "查询采购订单")
        self.assertEqual(response.messages[1].content, "已找到订单")

    def test_task_tool_call_is_serialized_as_delegation(self) -> None:
        """
        历史会话应将主 Agent 的 task 工具调用展示为子 Agent 任务委派。
        """
        messages = serialize_messages(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "task-1",
                            "name": "task",
                            "args": {
                                "subagent_type": "procurement_order",
                                "description": "查询供应商信息",
                            },
                        }
                    ],
                )
            ]
        )

        self.assertEqual(messages[0].role, "delegation")
        self.assertEqual(messages[0].source, "procurement_order")
        self.assertEqual(messages[0].args, "")
        self.assertEqual(messages[0].content, "查询供应商信息")

    async def test_restores_pending_interrupt_with_its_id(self) -> None:
        state = SimpleNamespace(
            values={"messages": []},
            interrupts=(SimpleNamespace(id="approval-1", value={
                "action_requests": [{"name": "create_order", "args": {}}],
                "review_configs": [{"action_name": "create_order", "allowed_decisions": ["approve", "reject"]}],
            }),),
        )
        with (
            patch("api.history.agent_loader.get_session", new=AsyncMock(return_value={})),
            patch("api.history.agent_loader.get_thread_state", new=AsyncMock(return_value=state)),
        ):
            response = await get_session_messages("thread-1", user_id="u1")
        self.assertEqual(response.interrupt["interrupt_id"], "approval-1")
        self.assertEqual(response.interrupt["interrupt_type"], "hitl_approval")
        self.assertEqual(response.interrupt["action_requests"][0]["name"], "create_order")
        self.assertIn("review_configs", response.interrupt)

    def test_completed_async_delegation_restores_task_id_and_done_status(self) -> None:
        task_id = "12fd2b03-f2c1-4b80-a8ca-9cb91bc43ccd"
        messages = serialize_messages([
            AIMessage(content="", tool_calls=[{
                "id": "call-1", "name": "start_async_task", "args": {"description": "report"},
            }]),
            ToolMessage(content=f"task_id: {task_id}", tool_call_id="call-1"),
            AIMessage(id=f"async-task-result:{task_id}", content="report", additional_kwargs={
                "source": "main", "async_task_id": task_id,
            }),
        ])
        self.assertEqual(messages[0].async_task_id, task_id)
        self.assertEqual(messages[0].tool_status, "done")
        self.assertEqual(messages[1].async_task_id, task_id)

    def test_failed_tool_results_remain_errors_in_history(self) -> None:
        for name in ["request_erp", "task", "start_async_task"]:
            messages = serialize_messages([
                AIMessage(content="", tool_calls=[{"id": "call", "name": name, "args": {}}]),
                ToolMessage(content="ERP unavailable", tool_call_id="call", name=name, status="error"),
            ])
            self.assertEqual(messages[0].tool_status, "error")
            self.assertEqual(messages[0].text, "ERP unavailable")
            self.assertIsNone(messages[0].async_task_id)

    def test_keeps_final_subagent_report_but_hides_internal_text(self) -> None:
        """历史显示同步任务回执，但不暴露子 Agent 逐步对话。"""
        messages = serialize_messages(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "task-1",
                            "name": "task",
                            "args": {"subagent_type": "procurement_order"},
                        }
                    ],
                ),
                ToolMessage(content="内部订单处理报告", tool_call_id="task-1"),
                AIMessage(
                    content="子 Agent 的内部文本",
                    additional_kwargs={"source": "procurement_order"},
                ),
                AIMessage(content="订单已创建。", additional_kwargs={"source": "main"}),
            ]
        )

        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].role, "delegation")
        self.assertEqual(messages[0].tool_status, "done")
        self.assertEqual(messages[0].text, "内部订单处理报告")
        self.assertEqual(messages[1].content, "订单已创建。")

    def test_async_delegation_remains_calling_after_task_submission(self) -> None:
        """异步任务的提交回执不是终态，历史恢复后必须继续显示运行中。"""
        messages = serialize_messages(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "async-task-1",
                            "name": "start_async_task",
                            "args": {
                                "subagent_type": "procurement_analyst",
                                "description": "生成采购趋势图",
                            },
                        }
                    ],
                ),
                ToolMessage(
                    content="任务已创建：12fd2b03-f2c1-4b80-a8ca-9cb91bc43ccd",
                    tool_call_id="async-task-1",
                ),
            ]
        )

        self.assertEqual(messages[0].role, "delegation")
        self.assertEqual(messages[0].tool_status, "calling")
        self.assertEqual(messages[0].text, "")
        self.assertEqual(messages[0].async_task_id, "12fd2b03-f2c1-4b80-a8ca-9cb91bc43ccd")

    def test_keeps_main_tool_arguments_in_history(self) -> None:
        """普通工具调用恢复后仍应显示主 Agent 实际提交的参数。"""
        messages = serialize_messages(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "tool-1",
                            "name": "inventory_query",
                            "args": {"part_id": 42},
                        }
                    ],
                )
            ]
        )

        self.assertEqual(messages[0].role, "tool")
        self.assertEqual(messages[0].args, "{'part_id': 42}")

    def test_legacy_png_chart_artifact_is_restored_as_an_image_resource(self) -> None:
        """历史 PNG 资源恢复后必须保持静态图片语义。"""
        artifact_id = "b" * 32
        messages = serialize_messages(
            [
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "id": "chart-1",
                            "name": "generate_visualization",
                            "args": {"chart_type": "bar", "chart_config": {}},
                        }
                    ],
                ),
                ToolMessage(
                    content=json.dumps(
                        {
                            "type": "chart_artifact",
                            "artifact_id": artifact_id,
                            "mime_type": "image/png",
                            "message": "图表已生成，图片资源已持久化。",
                        },
                        ensure_ascii=False,
                    ),
                    tool_call_id="chart-1",
                ),
            ]
        )

        self.assertEqual(messages[0].visualization.artifact_id, artifact_id)
        self.assertEqual(messages[0].visualization.kind, "image")
        self.assertEqual(messages[0].visualization.src, f"/visualizations/{artifact_id}")
        self.assertEqual(messages[0].text, "图表已生成，图片资源已持久化。")

    def test_main_async_result_restores_html_chart_after_refresh(self) -> None:
        """异步任务结果写入主 checkpoint 后，历史恢复必须保留 HTML 图表入口。"""
        artifact_id = "c" * 32
        messages = serialize_messages(
            [
                AIMessage(
                    id="async-task-result:task-1",
                    content=[
                        {"type": "text", "text": "图表已生成。"},
                        {
                            "type": "chart_artifact",
                            "artifact_id": artifact_id,
                            "mime_type": "text/html",
                        },
                    ],
                    additional_kwargs={"source": "main"},
                )
            ]
        )

        self.assertEqual(messages[0].id, "async-task-result:task-1")
        self.assertEqual(messages[0].source, "main")
        self.assertEqual(messages[0].visualization.kind, "link")
        self.assertEqual(messages[0].visualization.src, f"/visualizations/{artifact_id}")

    def test_sandbox_report_is_restored_as_a_user_scoped_download(self) -> None:
        """报告正文不进历史，但同一用户重开会话时仍可下载沙箱文件。"""
        report_id = "d" * 32
        messages = serialize_messages(
            [
                AIMessage(
                    id="async-task-result:task-1",
                    content=[
                        {
                            "type": "sandbox_report",
                            "report_id": report_id,
                            "label": "下载采购分析报告",
                        }
                    ],
                    additional_kwargs={"source": "main"},
                )
            ],
            user_id="user-2",
        )

        self.assertEqual(messages[0].content, "")
        self.assertEqual(messages[0].report.report_id, report_id)
        self.assertEqual(
            messages[0].report.download_src,
            f"/analysis/reports/{report_id}?user_id=user-2",
        )

class ThreadHistoryReaderTests(unittest.IsolatedAsyncioTestCase):
    """确保历史恢复通过已编译状态图重放 DeltaChannel。"""

    async def test_recovers_child_interrupt_after_parent_stream_was_closed_early(self) -> None:
        """
        旧版流已损坏父中断记录时，只恢复当前活动子图中的未完成中断。
        """
        checkpointer = InMemorySaver()

        def ask(state):
            result = interrupt({"type": "information_request", "information_needed": "child question"})
            return {"messages": [AIMessage(content=str(result))]}

        child = StateGraph(MessagesState)
        child.add_node("ask", ask)
        child.add_edge(START, "ask")
        child.add_edge("ask", END)
        parent = StateGraph(MessagesState)
        parent.add_node("tools", child.compile())
        parent.add_edge(START, "tools")
        parent.add_edge("tools", END)
        agent = parent.compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": "early-closed-parent"}}
        stream = agent.astream({"messages": [HumanMessage(content="test")]}, config,
                              subgraphs=True, stream_mode="values", version="v2")
        async for event in stream:
            if event.get("interrupts"):
                break
        await stream.aclose()
        self.assertFalse((await agent.aget_state(config)).interrupts)

        minimal = StateGraph(MessagesState)
        minimal.add_node("tools", lambda state: {})
        minimal.add_edge(START, "tools")
        minimal.add_edge("tools", END)
        with patch("agent.history_reader.create_deep_agent", return_value=minimal.compile(checkpointer=checkpointer)):
            reader = ThreadHistoryReader(checkpointer=checkpointer)
        recovered = await reader.get_state("early-closed-parent")
        self.assertEqual(len(recovered.interrupts), 1)
        self.assertEqual(recovered.interrupts[0].value["information_needed"], "child question")
        await agent.ainvoke(Command(resume={recovered.interrupts[0].id: "finished"}), config)
        finished = await reader.get_state("early-closed-parent")
        self.assertFalse(finished.interrupts)
        self.assertFalse(finished.next)

    async def test_restores_interrupt_from_node_absent_in_reader_graph(self) -> None:
        """最小读图不含审批节点时，也必须保留 SDK 写入 checkpoint 的中断。"""
        checkpointer = InMemorySaver()

        def approval(state):
            interrupt({"type": "information_request", "information_needed": "confirm"})
            return {}

        graph = StateGraph(MessagesState)
        graph.add_node("custom_approval", approval)
        graph.add_edge(START, "custom_approval")
        graph.add_edge("custom_approval", END)
        config = {"configurable": {"thread_id": "paused-thread"}}
        await graph.compile(checkpointer=checkpointer).ainvoke(
            {"messages": [HumanMessage(content="hello")]}, config,
        )

        read_graph = StateGraph(MessagesState)
        read_graph.add_node("model", lambda state: {})
        read_graph.add_edge(START, "model")
        read_graph.add_edge("model", END)
        with patch("agent.history_reader.create_deep_agent", return_value=read_graph.compile(checkpointer=checkpointer)):
            reader = ThreadHistoryReader(checkpointer=checkpointer)
        state = await reader.get_state("paused-thread")
        self.assertEqual(state.values["messages"][0].content, "hello")
        self.assertEqual(len(state.interrupts), 1)
        self.assertEqual(state.interrupts[0].value["information_needed"], "confirm")
        self.assertTrue(state.interrupts[0].id)

    async def test_get_messages_replays_state_for_thread(self) -> None:
        expected_messages = ["user message", "assistant message"]
        state_graph = MagicMock()
        state_graph.aget_state = AsyncMock(
            return_value=SimpleNamespace(values={"messages": expected_messages}, config={})
        )

        with patch("agent.history_reader.create_deep_agent", return_value=state_graph):
            reader = ThreadHistoryReader(checkpointer=MagicMock())

        messages = await reader.get_messages("thread-1")

        self.assertEqual(messages, expected_messages)
        state_graph.aget_state.assert_awaited_once_with(
            {"configurable": {"thread_id": "thread-1"}}
        )
