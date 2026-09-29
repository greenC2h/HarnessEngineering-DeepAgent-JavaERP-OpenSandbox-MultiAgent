"""图表 MCP 工具压缩适配层的单元测试。"""

from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agent.tools.chart_tools import create_chart_tools


class ChartToolTests(unittest.IsolatedAsyncioTestCase):
    """验证图表目录、Schema 查询和统一生成入口。"""

    def setUp(self) -> None:
        class FakeSchema:
            @classmethod
            def model_json_schema(cls):
                return {
                    "type": "object",
                    "properties": {
                        "data": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "category": {"type": "string"},
                                    "value": {"type": "number"},
                                },
                                "required": ["category", "value"],
                            },
                        }
                    },
                    "required": ["data"],
                }

        self.chart_tool = SimpleNamespace(
            name="generate_bar_chart",
            description="Generate a bar chart for comparing categories.",
            args_schema=FakeSchema,
            ainvoke=AsyncMock(return_value="<html><body><h1>Chart</h1></body></html>"),
        )
        self.get_spec, self.generate = create_chart_tools([self.chart_tool])

    def test_exposes_only_two_compact_tools(self) -> None:
        """底层工具应被压缩成 Schema 查询和统一生成两个入口。"""
        self.assertEqual(self.get_spec.name, "get_chart_spec")
        self.assertEqual(self.generate.name, "generate_visualization")
        self.assertIn("bar", self.get_spec.description)
        self.assertIn("bar", self.generate.description)

    def test_get_chart_spec_returns_schema_and_minimum_example(self) -> None:
        """Schema 查询应返回底层字段定义和可读的最小示例。"""
        spec = json.loads(self.get_spec.invoke({"chart_type": "bar"}))

        self.assertEqual(spec["tool_name"], "generate_bar_chart")
        self.assertEqual(spec["input_schema"]["required"], ["data"])
        self.assertEqual(
            spec["minimum_example"],
            {"data": [{"category": "示例", "value": 1}]},
        )

    async def test_generate_visualization_returns_persistent_artifact_record(self) -> None:
        """统一入口应保存 HTML 并只把轻量资源记录返回给模型。"""
        config = {"data": [{"category": "A", "value": 1}]}

        with patch(
            "agent.tools.chart_tools.save_visualization",
            return_value={
                "artifact_id": "a" * 32,
                "mime_type": "text/html",
                "path": "runtime/visualizations/test.html",
            },
        ) as save_visualization:
            result = await self.generate.ainvoke(
                {"chart_type": "bar", "chart_config": config}
            )

        artifact = json.loads(result)
        self.assertEqual(artifact["type"], "chart_artifact")
        self.assertEqual(artifact["artifact_id"], "a" * 32)
        self.assertNotIn("base64", artifact)
        self.assertEqual(artifact["mime_type"], "text/html")
        save_visualization.assert_called_once_with(
            b"<html><body><h1>Chart</h1></body></html>",
            "text/html",
        )
        self.chart_tool.ainvoke.assert_awaited_once_with(
            {**config, "format": "html"}
        )

    async def test_generate_visualization_does_not_expose_html_url(self) -> None:
        """HTML URL 应在工具边界内下载，而不是进入 Agent 消息。"""
        self.chart_tool.ainvoke.return_value = "http://charts.example/chart.html"

        with (
            patch(
                "agent.tools.chart_tools.httpx.AsyncClient",
            ) as client_class,
            patch(
                "agent.tools.chart_tools.save_visualization",
                return_value={
                    "artifact_id": "b" * 32,
                    "mime_type": "text/html",
                    "path": "runtime/visualizations/test.html",
                },
            ) as save_visualization,
        ):
            response = client_class.return_value.__aenter__.return_value
            response.get = AsyncMock(
                return_value=SimpleNamespace(
                    text="<html><body>chart</body></html>",
                    content=b"",
                    headers={},
                    raise_for_status=lambda: None,
                )
            )
            result = await self.generate.ainvoke(
                {"chart_type": "bar", "chart_config": {"data": []}}
            )

        artifact = json.loads(result)
        self.assertEqual(artifact["type"], "chart_artifact")
        self.assertNotIn("html_url", str(result))
        self.assertNotIn("chart.html", str(result))
        save_visualization.assert_called_once_with(
            b"<html><body>chart</body></html>",
            "text/html",
        )

    async def test_unknown_chart_type_returns_error_without_tool_call(self) -> None:
        """未知类型应返回可读错误且不触发远端调用。"""
        result = json.loads(
            await self.generate.ainvoke(
                {"chart_type": "unknown", "chart_config": {}}
            )
        )

        self.assertEqual(result["error"], "未知图表类型: unknown")
        self.chart_tool.ainvoke.assert_not_called()
