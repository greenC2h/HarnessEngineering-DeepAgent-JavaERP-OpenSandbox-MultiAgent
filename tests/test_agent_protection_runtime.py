"""用离线模型和真实 LangGraph 验证保护中间件的运行、恢复和压缩边界。"""

from __future__ import annotations

import os
import unittest
from collections.abc import Sequence
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from deepagents import (
    GeneralPurposeSubagentProfile,
    HarnessProfile,
    create_deep_agent,
    register_harness_profile,
)
from deepagents.backends import StateBackend
from deepagents.middleware.summarization import SummarizationMiddleware
from deepagents.profiles.harness import harness_profiles
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, ModelRequest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool, tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import Field

from agent.config import SUMMARY_MODEL
from agent.middlewares.agent_protection import (
    COMPACTION_SYSTEM_PROMPT,
    build_agent_protection_middleware,
)
from agent.middlewares.context_injection import ContextInjectionMiddleware


class RecordingChatModel(FakeMessagesListChatModel):
    """记录实际模型输入，耗尽脚本即失败，避免循环响应掩盖多余调用。"""

    model_name: str = "protection-runtime:offline"
    requests: list[list[BaseMessage]] = Field(default_factory=list)

    def bind_tools(
        self, tools: Sequence[BaseTool | dict[str, Any] | Any], **kwargs: Any
    ) -> RecordingChatModel:
        """接受真实 Agent 的工具绑定，由图负责实际工具调度。
        """
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """保存模型可见视图，并为每次脚本响应分配独立消息标识。
        """
        index = len(self.requests)
        self.requests.append([message.model_copy(deep=True) for message in messages])
        if index >= len(self.responses):
            raise AssertionError("保护中间件未按预期终止：模型响应脚本已耗尽")
        response = self.responses[index].model_copy(deep=True)
        response.id = f"response-{index}"
        if isinstance(response, AIMessage):
            for number, call in enumerate(response.tool_calls):
                call["id"] = f"call-{index}-{number}"
        return ChatResult(generations=[ChatGeneration(message=response)])


def tool_response(count: int = 1, name: str = "probe") -> AIMessage:
    """构造由真实工具节点执行的模型工具请求。
    """
    return AIMessage(
        content="",
        tool_calls=[
            {"name": name, "args": {}, "id": f"planned-{index}"}
            for index in range(count)
        ],
    )


class AgentProtectionRuntimeTests(unittest.IsolatedAsyncioTestCase):
    """仅使用内存 checkpoint/backend，覆盖主、子预算对应的真实图执行。"""

    def setUp(self) -> None:
        """隔离追踪与测试模型 profile，禁用 DeepAgents 默认子 Agent。
        """
        self.enterContext(
            patch.dict(os.environ, {"LANGSMITH_TRACING": "false", "LANGCHAIN_TRACING_V2": "false"})
        )
        self.enterContext(patch.dict(harness_profiles._HARNESS_PROFILES))
        register_harness_profile(
            "protection-runtime:offline",
            HarnessProfile(general_purpose_subagent=GeneralPurposeSubagentProfile(enabled=False)),
        )
        self.executed: list[str] = []

        @tool
        async def probe() -> str:
            """返回离线探针结果并记录真实工具执行。
            """
            self.executed.append("probe")
            return "probe-ok"

        @tool
        async def review() -> str:
            """记录经人工批准后执行的离线工具。
            """
            self.executed.append("review")
            return "review-ok"

        self.tools = [probe, review]

    def build_graph(
        self,
        responses: list[BaseMessage],
        *,
        deep: bool,
        model_limit: int = 12,
        tool_limit: int = 16,
        hitl: bool = False,
        trigger: int | None = None,
        summary_responses: list[BaseMessage] | None = None,
    ) -> tuple[Any, RecordingChatModel, RecordingChatModel, dict[str, Any]]:
        """构建真实图；低阈值仅替换测试 factory，保留 SDK 摘要执行路径。
        """
        model = RecordingChatModel(responses=responses)
        summary = RecordingChatModel(
            responses=summary_responses or [AIMessage(content="summary-marker")]
        )
        backend = StateBackend()

        def low_threshold_factory(model: Any, backend: Any) -> SummarizationMiddleware:
            """通过官方构造参数缩小触发门槛，保留默认摘要提示词。
            """
            return SummarizationMiddleware(
                model=model,
                backend=backend,
                trigger=("messages", trigger),
                keep=("messages", 2),
            )

        kwargs = {
            "backend": backend,
            "summary_model": summary,
            "model_run_limit": model_limit,
            "tool_run_limit": tool_limit,
            "enable_compaction_tool": deep,
        }
        if trigger is None:
            middleware = build_agent_protection_middleware(**kwargs)
        else:
            with patch(
                "agent.middlewares.agent_protection.create_summarization_middleware",
                new=low_threshold_factory,
            ):
                middleware = build_agent_protection_middleware(**kwargs)
        if hitl:
            middleware.append(HumanInTheLoopMiddleware(interrupt_on={"review": True}))
        options = {
            "model": model,
            "tools": self.tools,
            "middleware": middleware,
            "checkpointer": InMemorySaver(),
        }
        graph = (
            create_deep_agent(**options, backend=backend)
            if deep
            else create_agent(**options)
        )
        # 递归预算高于正常保护终止所需步数；若保护失效，有限脚本会立即报错。
        config = {"configurable": {"thread_id": "runtime-test"}, "recursion_limit": 300}
        return graph, model, summary, config

    def assert_pairs(self, messages: list[BaseMessage]) -> None:
        """每个工具请求必须恰好有一个结果，且不能跨越下一条普通消息。
        """
        pending: set[str] = set()
        for message in messages:
            if isinstance(message, ToolMessage):
                self.assertIn(message.tool_call_id, pending)
                pending.remove(message.tool_call_id)
            else:
                self.assertFalse(pending, f"未完成工具调用：{pending}")
                if isinstance(message, AIMessage):
                    ids = [call["id"] for call in message.tool_calls]
                    self.assertEqual(len(ids), len(set(ids)))
                    pending.update(ids)
        self.assertFalse(pending)

    async def assert_finished(self, graph: Any, config: dict[str, Any]) -> dict[str, Any]:
        """检查 checkpoint 已正常结束，且原始消息没有悬空工具调用。
        """
        snapshot = await graph.aget_state(config)
        self.assertEqual(snapshot.next, ())
        self.assertFalse(any(task.interrupts for task in snapshot.tasks))
        self.assert_pairs(snapshot.values["messages"])
        return snapshot.values

    async def check_limit(self, model_limit: int, tool_limit: int, *, tools: bool) -> None:
        """两种公开 factory 均执行相同预算，不通过属性推断是否生效。
        """
        for deep in (False, True):
            with self.subTest(deep=deep):
                self.executed.clear()
                calls = tool_limit // 2 + 1 if tools else model_limit
                graph, model, summary, config = self.build_graph(
                    [tool_response(2 if tools else 1) for _ in range(calls)],
                    deep=deep,
                    model_limit=model_limit,
                    tool_limit=tool_limit,
                )
                result = await graph.ainvoke({"messages": [HumanMessage(content="执行探针")]}, config)
                self.assertEqual(len(model.requests), calls)
                self.assertEqual(len(self.executed), tool_limit if tools else model_limit)
                expected = (
                    f"Tool call limit reached: run limit exceeded ({tool_limit + 2}/{tool_limit} calls)."
                    if tools
                    else f"Model call limits exceeded: run limit ({model_limit}/{model_limit})"
                )
                self.assertEqual(result["messages"][-1].content, expected)
                self.assertEqual(len(summary.requests), 0)
                if tools:
                    errors = [m for m in result["messages"] if isinstance(m, ToolMessage) and m.status == "error"]
                    self.assertEqual(len(errors), 2)
                await self.assert_finished(graph, config)

    async def test_main_model_limit_stops_after_twelve_calls(self) -> None:
        """主 Agent 的 12/16 预算在第十二次模型调用后正常结束。
        """
        await self.check_limit(12, 16, tools=False)

    async def test_main_tool_limit_stops_after_sixteen_executions(self) -> None:
        """成对工具调用先达到主 Agent 的十六次工具预算。
        """
        await self.check_limit(12, 16, tools=True)

    async def test_subagent_model_limit_stops_after_ten_calls(self) -> None:
        """子 Agent 的 10/10 预算在第十次模型调用后正常结束。
        """
        await self.check_limit(10, 10, tools=False)

    async def test_subagent_tool_limit_stops_after_ten_executions(self) -> None:
        """成对工具调用先达到子 Agent 的十次工具预算。
        """
        await self.check_limit(10, 10, tools=True)

    async def test_new_runs_reset_both_budgets_with_same_checkpoint(self) -> None:
        """同一线程连续两轮均可用满模型或工具预算，历史累计不阻断新轮。
        """
        for model_limit, tool_limit in ((12, 16), (10, 10)):
            for tools in (False, True):
                with self.subTest(model_limit=model_limit, tools=tools):
                    self.executed.clear()
                    calls = tool_limit // 2 + 1 if tools else model_limit
                    graph, model, _, config = self.build_graph(
                        [tool_response(2 if tools else 1) for _ in range(calls * 2)],
                        deep=True, model_limit=model_limit, tool_limit=tool_limit,
                    )
                    for run in (1, 2):
                        await graph.ainvoke({"messages": [HumanMessage(content=f"第 {run} 轮")]}, config)
                        self.assertEqual(len(model.requests), calls * run)
                        self.assertEqual(len(self.executed), (tool_limit if tools else model_limit) * run)
                        state = await self.assert_finished(graph, config)
                        self.assertNotIn("run_model_call_count", state)
                        self.assertNotIn("run_tool_call_count", state)

    async def test_hitl_resume_resets_model_budget(self) -> None:
        """HITL 恢复继续当前 run，预算包含中断前已经消耗的模型调用。

        LangGraph 的 ``Command(resume=...)`` 会恢复同一个运行，因而不能把
        恢复误当成新的 run；这个断言同时防止恢复后绕过模型调用上限。
        """
        for model_limit, tool_limit in ((12, 16), (10, 10)):
            with self.subTest(model_limit=model_limit):
                self.executed.clear()
                graph, model, _, config = self.build_graph(
                    [tool_response(name="review"), *[tool_response() for _ in range(model_limit)]],
                    deep=True, model_limit=model_limit, tool_limit=tool_limit, hitl=True,
                )
                paused = await graph.ainvoke({"messages": [HumanMessage(content="等待批准")]}, config)
                self.assertTrue(paused["__interrupt__"])
                self.assertEqual(len(model.requests), 1)
                self.assertEqual(self.executed, [])
                result = await graph.ainvoke(Command(resume={"decisions": [{"type": "approve"}]}), config)
                self.assertEqual(len(model.requests), model_limit)
                self.assertEqual(self.executed.count("review"), 1)
                self.assertEqual(self.executed.count("probe"), model_limit - 1)
                self.assertEqual(result["messages"][-1].content, f"Model call limits exceeded: run limit ({model_limit}/{model_limit})")
                await self.assert_finished(graph, config)

    async def test_hitl_resume_resets_tool_budget(self) -> None:
        """恢复后先前两次工具执行不占预算，待批准工具仍会计入新预算。
        """
        for model_limit, tool_limit in ((12, 16), (10, 10)):
            with self.subTest(tool_limit=tool_limit):
                self.executed.clear()
                graph, model, _, config = self.build_graph(
                    [tool_response(2), tool_response(name="review"), tool_response(tool_limit - 1), tool_response()],
                    deep=True, model_limit=model_limit, tool_limit=tool_limit, hitl=True,
                )
                paused = await graph.ainvoke({"messages": [HumanMessage(content="先查询再批准")]}, config)
                self.assertTrue(paused["__interrupt__"])
                self.assertEqual(len(model.requests), 2)
                self.assertEqual(self.executed, ["probe", "probe"])
                result = await graph.ainvoke(Command(resume={"decisions": [{"type": "approve"}]}), config)
                self.assertEqual(len(model.requests), 4)
                self.assertEqual(len(self.executed), tool_limit + 2)
                self.assertEqual(self.executed.count("review"), 1)
                self.assertEqual(result["messages"][-1].content, f"Tool call limit reached: run limit exceeded ({tool_limit + 1}/{tool_limit} calls).")
                await self.assert_finished(graph, config)

    async def test_overflowing_batch_also_cancels_pending_allowed_tool(self) -> None:
        """剩余一个名额却请求两个工具时，end 语义取消整个批次并补齐结果。
        """
        graph, model, _, config = self.build_graph(
            [tool_response(15), tool_response(2)], deep=True,
        )
        result = await graph.ainvoke({"messages": [HumanMessage(content="并发越界")]}, config)
        self.assertEqual(len(model.requests), 2)
        self.assertEqual(len(self.executed), 15)
        errors = [m for m in result["messages"] if isinstance(m, ToolMessage) and m.status == "error"]
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("same batch" in message.content for message in errors))
        await self.assert_finished(graph, config)

    @staticmethod
    def history() -> list[BaseMessage]:
        """创建包含业务 ID、旧工具配对和长中间过程的最小摘要历史。
        """
        return [
            HumanMessage(content="订单 PO-42；task_id=task-17；artifact_id=chart-9；审批待确认。"),
            AIMessage(content="旧分析 " * 80),
            tool_response(),
            ToolMessage(content="历史库存", tool_call_id="planned-0"),
            AIMessage(content="已查明历史库存。"),
            HumanMessage(content="继续查证最新库存。"),
        ]

    async def test_automatic_summary_compresses_model_view_and_survives_checkpoint(self) -> None:
        """自动压缩保留工具配对、原始 checkpoint 和后续对话的摘要视图。
        """
        graph, model, summary, config = self.build_graph(
            [tool_response(2), AIMessage(content="本轮完成"), AIMessage(content="继续完成")],
            deep=True, trigger=8,
        )
        history = self.history()
        await graph.ainvoke({"messages": history}, config)
        self.assertEqual(len(summary.requests), 1)
        self.assertEqual(len(model.requests), 2)
        self.assertEqual(len(self.executed), 2)
        before = [m for m in model.requests[0] if m.type != "system"]
        after = [m for m in model.requests[1] if m.type != "system"]
        self.assertEqual(len(before), 6)
        self.assertEqual(len(after), 4)
        self.assertIn("summary-marker", after[0].content)
        self.assertIsInstance(after[1], AIMessage)
        self.assertEqual(len(after[1].tool_calls), 2)
        self.assert_pairs(after)
        state = await self.assert_finished(graph, config)
        self.assertEqual(len(state["messages"]), 10)
        self.assertEqual(state["messages"][0].content, history[0].content)
        event = state["_summarization_event"]
        self.assertEqual(event["cutoff_index"], 6)
        self.assertIn(event["file_path"], state["files"])
        archive = state["files"][event["file_path"]]["content"]
        if isinstance(archive, list):
            archive = "\n".join(archive)
        self.assertIn("PO-42", archive)

        # 记录已知边界：业务保留规则在主模型系统提示词，未进入摘要模型提示词。
        main_prompt = "\n".join(m.text for m in model.requests[0] if m.type == "system")
        summary_prompt = "\n".join(m.text for m in summary.requests[0])
        self.assertIn(COMPACTION_SYSTEM_PROMPT, main_prompt)
        self.assertNotIn(COMPACTION_SYSTEM_PROMPT, summary_prompt)
        self.assertNotIn("摘要必须保留", summary_prompt)
        for identifier in ("PO-42", "task-17", "chart-9"):
            self.assertIn(identifier, summary_prompt)

        await graph.ainvoke({"messages": [HumanMessage(content="继续下一阶段")]}, config)
        self.assertEqual(len(summary.requests), 1)
        self.assertEqual(len(model.requests), 3)
        self.assertIn("summary-marker", "\n".join(m.text for m in model.requests[-1]))
        self.assertNotIn(history[1].content, [m.content for m in model.requests[-1]])
        self.assert_pairs(model.requests[-1])
        final_state = await self.assert_finished(graph, config)
        self.assertEqual(final_state["_summarization_event"], event)
        self.assertEqual(final_state["messages"][-1].content, "继续完成")

    async def test_manual_then_automatic_compaction_share_persisted_history(self) -> None:
        """主动压缩后自动摘要承接同一摘要状态、归档文件和后续对话。
        """
        graph, model, summary, config = self.build_graph(
            [tool_response(name="compact_conversation"), AIMessage(content="压缩后继续"), AIMessage(content="新阶段完成")],
            deep=True, trigger=10,
            summary_responses=[AIMessage(content="manual-summary-marker"), AIMessage(content="automatic-summary-marker")],
        )
        result = await graph.ainvoke({"messages": self.history()}, config)
        self.assertEqual(len(summary.requests), 1)
        compact_result = next(m for m in result["messages"] if isinstance(m, ToolMessage) and m.tool_call_id == "call-0-0")
        self.assertIn("Conversation compacted.", compact_result.content)
        self.assertIn("manual-summary-marker", "\n".join(m.text for m in model.requests[1]))
        self.assert_pairs(model.requests[1])
        state = await self.assert_finished(graph, config)
        first_event = state["_summarization_event"]
        first_archive = state["files"][first_event["file_path"]]["content"]
        extra_history = [
            HumanMessage(content="下一阶段一"), AIMessage(content="阶段一结论"),
            HumanMessage(content="下一阶段二"), AIMessage(content="阶段二结论"),
            HumanMessage(content="继续汇总"),
        ]
        await graph.ainvoke({"messages": extra_history}, config)
        self.assertEqual(len(summary.requests), 2)
        self.assertEqual(len(model.requests), 3)
        self.assertIn("manual-summary-marker", "\n".join(m.text for m in summary.requests[1]))
        self.assertIn("automatic-summary-marker", "\n".join(m.text for m in model.requests[2]))
        self.assert_pairs(model.requests[2])
        final_state = await self.assert_finished(graph, config)
        final_event = final_state["_summarization_event"]
        self.assertGreater(final_event["cutoff_index"], first_event["cutoff_index"])
        self.assertEqual(final_event["file_path"], first_event["file_path"])
        final_archive = final_state["files"][final_event["file_path"]]["content"]
        self.assertGreater(len(final_archive), len(first_archive))
        self.assertEqual(final_archive[:len(first_archive)], first_archive)


class AgentProtectionMiddlewareTests(unittest.TestCase):
    """验证主 Agent 和子 Agent 可复用的中间件装配。"""

    def test_compaction_tool_shares_the_automatic_summarizer(self) -> None:
        """主动压缩工具必须复用自动摘要实例，避免两套摘要状态分离。"""
        middleware = build_agent_protection_middleware(
            backend=StateBackend(),
            summary_model=SUMMARY_MODEL,
            model_run_limit=3,
            tool_run_limit=4,
            enable_compaction_tool=True,
        )

        self.assertEqual(
            [item.name for item in middleware],
            [
                "SummarizationMiddleware",
                "SummarizationToolMiddleware",
                "ModelCallLimitMiddleware",
                "ToolCallLimitMiddleware",
            ],
        )
        self.assertIs(middleware[1]._summarization, middleware[0])
        self.assertEqual([tool.name for tool in middleware[1].tools], ["compact_conversation"])
        self.assertEqual(middleware[2].run_limit, 3)
        self.assertEqual(middleware[3].run_limit, 4)

    def test_subagent_protection_does_not_expose_compaction_tool(self) -> None:
        """子 Agent 仍自动摘要和受限，但不会获得主 Agent 的主动压缩工具。"""
        middleware = build_agent_protection_middleware(
            backend=StateBackend(),
            summary_model=SUMMARY_MODEL,
            model_run_limit=3,
            tool_run_limit=4,
        )

        self.assertEqual(
            [item.name for item in middleware],
            [
                "SummarizationMiddleware",
                "ModelCallLimitMiddleware",
                "ToolCallLimitMiddleware",
            ],
        )


class ContextInjectionMiddlewareTests(unittest.TestCase):
    """验证运行时用户身份仅进入模型系统提示词。"""

    def test_injects_user_identity_and_preferences_path(self) -> None:
        """模型请求应包含当前用户身份和用户隔离的偏好文件路径。"""
        request = ModelRequest(
            model=MagicMock(),
            messages=[],
            system_message=SystemMessage(content="原始规则"),
            runtime=SimpleNamespace(
                context=SimpleNamespace(user_id="u1", username="张三"),
            ),
        )

        injected = ContextInjectionMiddleware()._inject_context(request)

        self.assertIn("原始规则", injected.system_message.content)
        self.assertIn("user_id: u1", injected.system_message.content)
        self.assertIn("username: 张三", injected.system_message.content)
        self.assertIn("/memories/u1/preferences.md", injected.system_message.content)

    def test_skips_injection_without_user_id(self) -> None:
        """上下文不含用户标识时保持原模型请求不变。"""
        request = ModelRequest(
            model=MagicMock(),
            messages=[],
            system_message=SystemMessage(content="原始规则"),
            runtime=SimpleNamespace(context=SimpleNamespace(user_id="")),
        )

        self.assertIs(ContextInjectionMiddleware()._inject_context(request), request)


if __name__ == "__main__":
    unittest.main()
