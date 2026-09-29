"""对话 SSE 中断事件的单元测试。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

from api.chat import (
    _get_interrupt_values,
    _is_internal_middleware_stream,
    _is_subagent_stream,
    _get_stream_source,
    _get_subagent_name,
    _serialize_tool_args,
    _serialize_interrupt,
)


class ChatInterruptTests(unittest.TestCase):
    """确保框架中断可以稳定地转换为前端协议。"""

    def test_reads_top_level_interrupt_values(self) -> None:
        """
        values 事件顶层的 interrupts 应还原其 value 字段。
        """
        value = {"type": "information_request", "information_needed": "物料 ID"}

        interrupts = _get_interrupt_values(
            {"type": "values", "interrupts": [SimpleNamespace(value=value)]}
        )

        self.assertEqual(interrupts, [value])

    def test_serializes_generic_information_request(self) -> None:
        """通用补充请求不应依赖订单字段。"""
        event = _serialize_interrupt(
            {
                "type": "information_request",
                "information_needed": "请确认报表统计周期",
                "context": "当前选择了采购金额趋势图",
            },
            "thread-1",
        )

        self.assertEqual(event["interrupt_type"], "information_request")
        self.assertEqual(event["information_needed"], "请确认报表统计周期")
        self.assertEqual(event["context"], "当前选择了采购金额趋势图")

    def test_serializes_hitl_approval_interrupt(self) -> None:
        """
        工具审批中断应透传待审批的 action_requests。
        """
        actions = [{"name": "order_create", "args": {"order_detail": []}}]

        event = _serialize_interrupt({"action_requests": actions}, "thread-1")

        self.assertEqual(event["interrupt_type"], "hitl_approval")
        self.assertEqual(event["action_requests"], actions)

    def test_marks_nested_graph_events_as_subagent_output(self) -> None:
        """
        子图命名空间中的事件应使用子 Agent 来源标识。
        """
        source = _get_stream_source({"ns": ("tools:task:child",)})

        self.assertEqual(source, "subagent")

    def test_uses_named_subagent_metadata_when_available(self) -> None:
        """
        DeepAgents 元数据存在时，流事件应保留子 Agent 原名。
        """
        source = _get_stream_source(
            {"ns": ("tools:task:child",)},
            {"lc_agent_name": "procurement_analyst"},
        )

        self.assertEqual(source, "procurement_analyst")

    def test_hides_regular_subagent_events_from_the_user_stream(self) -> None:
        """子图文本和工具事件不应作为用户消息发送。"""
        self.assertTrue(_is_subagent_stream("procurement_order"))
        self.assertTrue(_is_subagent_stream("subagent"))
        self.assertFalse(_is_subagent_stream("main"))

    def test_hides_memory_update_model_events_from_the_user_stream(self) -> None:
        """近期记忆摘要模型的输出不得被误当作主 Agent 文本显示。"""
        self.assertTrue(
            _is_internal_middleware_stream(
                {"langgraph_node": "MemoryUpdateMiddleware.after_agent"}
            )
        )
        self.assertFalse(_is_internal_middleware_stream({"langgraph_node": "model"}))

    def test_reads_subagent_name_from_task_arguments(self) -> None:
        """task 参数应把子 Agent 原名传入 SSE 事件。"""
        self.assertEqual(
            _get_subagent_name("{'subagent_type': 'procurement_analyst'}"),
            "procurement_analyst",
        )

    def test_serializes_structured_tool_args_as_json(self) -> None:
        """前端应能从 SSE 参数中稳定读取任务描述。"""
        self.assertEqual(
            _serialize_tool_args({"subagent_type": "procurement_order", "description": "查询订单"}),
            '{"subagent_type": "procurement_order", "description": "查询订单"}',
        )
