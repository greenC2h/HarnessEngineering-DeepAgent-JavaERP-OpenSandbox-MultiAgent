"""MCP 工具分组加载的单元测试。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

from agent.tools.mcp_client import load_chart_mcp_tools, load_mcp_tools


class McpClientTests(unittest.IsolatedAsyncioTestCase):
    """验证公共工具和 Java ERP 工具保持独立分组。"""

    async def test_load_mcp_tools_returns_tools_by_server_group(self) -> None:
        """两个 MCP Server 的工具应按调用方指定的组分别返回。"""
        common_tools = [SimpleNamespace(name="web_search")]
        order_tools = [
            SimpleNamespace(name="supplier_query"),
            SimpleNamespace(name="order_create"),
        ]
        client = MagicMock()
        client.get_tools = AsyncMock(
            side_effect=lambda *, server_name: (
                common_tools if server_name == "bing-search" else order_tools
            )
        )

        with patch(
            "agent.tools.mcp_client.MultiServerMCPClient",
            return_value=client,
        ) as client_factory:
            loaded_common_tools, loaded_order_tools = await load_mcp_tools(
                common_server_config={"bing-search": {"url": "https://common.example/mcp"}},
                order_server_config={"erp-api": {"url": "http://erp.example/mcp"}},
            )

        self.assertEqual(loaded_common_tools, common_tools)
        self.assertEqual(loaded_order_tools, order_tools)
        self.assertEqual(client_factory.call_count, 2)
        client.get_tools.assert_has_awaits(
            [call(server_name="bing-search"), call(server_name="erp-api")]
        )

    async def test_load_mcp_tools_exposes_bing_search_as_web_search(self) -> None:
        """公共搜索 MCP 的实现名称必须符合子 Agent 的统一工具契约。"""
        common_tools = [SimpleNamespace(name="bing_search")]
        client = MagicMock()
        client.get_tools = AsyncMock(return_value=common_tools)

        with patch(
            "agent.tools.mcp_client.MultiServerMCPClient",
            return_value=client,
        ):
            loaded_common_tools, loaded_order_tools = await load_mcp_tools(
                common_server_config={"bing-search": {"url": "https://common.example/mcp"}},
                order_server_config={},
            )

        self.assertEqual([tool.name for tool in loaded_common_tools], ["web_search"])
        self.assertEqual(loaded_order_tools, [])

    async def test_load_chart_mcp_tools_returns_chart_tools(self) -> None:
        """图表 MCP 工具应独立于公共和采购工具组加载。"""
        chart_tools = [SimpleNamespace(name="generate_bar_chart")]
        client = MagicMock()
        client.get_tools = AsyncMock(return_value=chart_tools)

        with patch(
            "agent.tools.mcp_client.MultiServerMCPClient",
            return_value=client,
        ) as client_factory:
            loaded_tools = await load_chart_mcp_tools(
                {"charts-mcp": {"url": "https://charts.example/mcp"}}
            )

        self.assertEqual(loaded_tools, chart_tools)
        client_factory.assert_called_once_with(
            {"charts-mcp": {"url": "https://charts.example/mcp"}}
        )
        client.get_tools.assert_awaited_once_with(server_name="charts-mcp")
