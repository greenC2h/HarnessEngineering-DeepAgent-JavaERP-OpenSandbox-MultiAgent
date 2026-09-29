"""采购订单子 Agent 配置的单元测试。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from agent.main_agent import create_main_agent
from agent.subagents.loader import load_subagent


CONFIG_PATH = "src/agent/subagents/configs/procurement_order.yaml"


class ProcurementOrderSubagentTests(unittest.TestCase):
    """确保订单子 Agent 接收订单、搜索和人工补充工具。"""

    def test_loads_java_order_tools_and_interrupt_configuration(self) -> None:
        """
        YAML 配置应保留订单审批规则，并补入本地通用补充工具。
        """
        available_tools = [
            SimpleNamespace(name="order_create"),
            SimpleNamespace(name="order_update"),
            SimpleNamespace(name="order_search_details"),
            SimpleNamespace(name="web_search"),
        ]

        subagent = load_subagent(CONFIG_PATH, available_tools, local_tools=[
            SimpleNamespace(name="request_additional_info"),
        ])

        self.assertEqual(subagent["name"], "procurement_order")
        self.assertEqual(
            [tool.name for tool in subagent["tools"]],
            [
                "order_create",
                "order_update",
                "order_search_details",
                "web_search",
                "request_additional_info",
            ],
        )
        self.assertEqual(
            subagent["interrupt_on"]["order_create"]["allowed_decisions"],
            ["approve", "reject"],
        )
        self.assertEqual(
            subagent["interrupt_on"]["order_update"]["allowed_decisions"],
            ["approve", "reject"],
        )
        self.assertIn("不得先用普通文本要求用户", subagent["system_prompt"])
        self.assertEqual(
            subagent["skills"],
            ["/skills/subagents/procurement_order/"],
        )

    def test_rejects_missing_configured_java_tool(self) -> None:
        """
        Java MCP 工具不完整时不能构造会在运行时失败的子 Agent。
        """
        java_tools = [SimpleNamespace(name="order_create")]

        with self.assertRaisesRegex(ValueError, "order_search_details"):
            load_subagent(CONFIG_PATH, java_tools, local_tools=[
                SimpleNamespace(name="request_additional_info"),
            ])


class MainAgentSubagentTests(unittest.IsolatedAsyncioTestCase):
    """验证默认通用 Agent、同步订单和异步采购分析的注册边界。"""

    async def test_registers_common_information_tool_on_main_and_order_subagent(self) -> None:
        common_tool = SimpleNamespace(name="web_search")
        order_tools = [
            SimpleNamespace(name="order_create"),
            SimpleNamespace(name="order_update"),
            SimpleNamespace(name="order_search_details"),
        ]
        created_agent = MagicMock()
        sandbox_backend = MagicMock()

        with (
            patch(
                "agent.main_agent.load_mcp_tools",
                new=AsyncMock(return_value=([common_tool], order_tools)),
            ),
            patch("agent.main_agent.create_deep_agent", return_value=created_agent) as factory,
            patch("agent.main_agent.create_skill_management_tools", return_value=[]) as skill_factory,
        ):
            result = await create_main_agent(
                {"configurable": {"user_id": "u1", "username": "张三"}},
                store=MagicMock(),
                checkpointer=MagicMock(),
                sandbox_backend=sandbox_backend,
            )

        self.assertIs(result, created_agent)
        self.assertIs(skill_factory.call_args.kwargs["sandbox_backend"], sandbox_backend)
        arguments = factory.call_args.kwargs
        self.assertEqual(
            [tool.name for tool in arguments["tools"]],
            ["web_search", "start_async_task", "request_additional_info"],
        )
        child = arguments["subagents"][0]
        self.assertEqual(child["name"], "procurement_order")
        self.assertEqual(
            [tool.name for tool in child["tools"]],
            [
                "order_create",
                "order_update",
                "order_search_details",
                "web_search",
                "request_additional_info",
            ],
        )
        self.assertNotIn(
            "general-purpose",
            [subagent["name"] for subagent in arguments["subagents"]],
        )
        async_subagent = arguments["subagents"][1]
        self.assertEqual(async_subagent["name"], "procurement_analyst")

        self.assertEqual(
            [middleware.name for middleware in child["middleware"]],
            [
                "SkillsMiddleware",
                "SummarizationMiddleware",
                "ModelCallLimitMiddleware",
                "ToolCallLimitMiddleware",
            ],
        )
        self.assertEqual(len(arguments["subagents"]), 2)
        self.assertIn("start_async_task", arguments["system_prompt"])
        self.assertEqual(
            [middleware.name for middleware in arguments["middleware"]],
            [
                "context_injection",
                "SkillsMiddleware",
                "SummarizationMiddleware",
                "SummarizationToolMiddleware",
                "ModelCallLimitMiddleware",
                "ToolCallLimitMiddleware",
                "skill_management_visibility",
                "MemoryUpdateMiddleware",
            ],
        )
