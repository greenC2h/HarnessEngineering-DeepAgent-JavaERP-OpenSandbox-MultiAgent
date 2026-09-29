"""异步图表任务状态接口测试。"""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from api.agent_loader import AgentLoader
from agent.schema import AsyncTaskBinding
from api.async_tasks import (
    _extract_report_path,
    _sanitize_task_content,
    extract_async_task_id,
    get_async_task_status,
)
from agent.backends.sandbox_proxy import SandboxBackendProxy
from agent.memory.prompts import system_prompt
from agent.subagents.async_registry import get_async_subagent_instructions
from langchain_core.tools import tool
from langgraph_sdk.runtime import _ExecutionRuntime, _ReadRuntime


def _configured_tool(name: str):
    """创建可被 DeepAgents 编译的最小工具，避免网络依赖。"""

    def test_tool() -> str:
        """测试用工具。"""
        return "ok"

    test_tool.__name__ = name
    return tool(test_tool)


REPORT_PATH = "/analysis/report_20260928_010203.md"


class AsyncTaskStatusTests(unittest.IsolatedAsyncioTestCase):
    """验证终态远程结果只经主会话投递。"""

    async def asyncSetUp(self) -> None:
        self.binding_patch = patch(
            "api.async_tasks.agent_loader.get_async_task_binding",
            new=AsyncMock(return_value=AsyncTaskBinding("task-1", "u1", "张三", "thread-1")),
        )
        self.binding_patch.start()
        self.addCleanup(self.binding_patch.stop)
        self.session_patch = patch("api.async_tasks.agent_loader.require_session", new=AsyncMock())
        self.session_patch.start()
        self.addCleanup(self.session_patch.stop)

    async def test_delivers_completed_chart_artifact_to_main_thread(self) -> None:
        """完成任务应将 artifact 投递主会话并返回给前端任务卡片。"""
        artifact_id = "a" * 32
        client = SimpleNamespace(
            runs=SimpleNamespace(
                list=AsyncMock(return_value=[{"status": "success", "run_id": "run-1"}])
            ),
            threads=SimpleNamespace(
                get_state=AsyncMock(
                    return_value=SimpleNamespace(
                        values={
                            "messages": [
                                {"role": "human", "content": "生成采购分析报告和趋势图"},
                                {
                                    "role": "tool",
                                    "content": json.dumps(
                                        {
                                            "type": "chart_artifact",
                                            "artifact_id": artifact_id,
                                            "mime_type": "text/html",
                                        },
                                    ),
                                },
                                {"role": "assistant", "content": f"分析完成。\nREPORT_PATH: {REPORT_PATH}"},
                            ]
                        }
                    )
                )
            ),
        )

        with (
            patch("api.async_tasks.get_client", return_value=client),
            patch(
                "api.async_tasks.agent_loader.register_sandbox_report",
                new=AsyncMock(return_value={"report_id": "b" * 32, "label": "下载采购分析报告"}),
            ) as register,
            patch(
                "api.async_tasks.agent_loader.publish_async_task_result",
                new=AsyncMock(return_value=True),
            ) as publish,
        ):
            response = await get_async_task_status("task-1", user_id="u1")

        self.assertTrue(response.done)
        self.assertTrue(response.delivered)
        self.assertIsNotNone(response.visualization)
        self.assertEqual(response.visualization.artifact_id, artifact_id)
        self.assertEqual(response.visualization.mime_type, "text/html")
        self.assertEqual(response.report.report_id, "b" * 32)
        register.assert_awaited_once_with("task-1", REPORT_PATH)
        self.assertEqual(publish.await_args.kwargs["report"]["report_id"], "b" * 32)

    async def test_chart_only_task_does_not_require_or_publish_report(self) -> None:
        """只要求图表时，成功终态不能凭空出现报告下载入口。"""
        artifact_id = "c" * 32
        client = SimpleNamespace(
            runs=SimpleNamespace(list=AsyncMock(return_value=[{"status": "success"}])) ,
            threads=SimpleNamespace(get_state=AsyncMock(return_value=SimpleNamespace(values={
                "messages": [
                    {"role": "human", "content": "基于采购订单画一个月度趋势图"},
                    {"role": "assistant", "content": json.dumps({
                        "type": "chart_artifact", "artifact_id": artifact_id, "mime_type": "text/html",
                    })},
                ],
            }))),
        )
        with (
            patch("api.async_tasks.get_client", return_value=client),
            patch("api.async_tasks.agent_loader.publish_async_task_result", new=AsyncMock(return_value=True)) as publish,
        ):
            response = await get_async_task_status("task-1", user_id="u1")

        self.assertEqual(response.status, "success")
        self.assertIsNone(response.report)
        self.assertEqual(response.result, "图表已生成。")
        self.assertIsNone(publish.await_args.kwargs["report"])

    async def test_report_request_without_report_path_remains_an_error(self) -> None:
        """明确要求报告但子 Agent 未写入文件时，不能伪装成成功。"""
        client = SimpleNamespace(
            runs=SimpleNamespace(list=AsyncMock(return_value=[{"status": "success"}])),
            threads=SimpleNamespace(get_state=AsyncMock(return_value=SimpleNamespace(values={
                "messages": [
                    {"role": "human", "content": "生成采购分析报告"},
                    {"role": "assistant", "content": "分析完成，但未写入报告"},
                ],
            }))),
        )
        with (
            patch("api.async_tasks.get_client", return_value=client),
            patch("api.async_tasks.agent_loader.publish_async_task_result", new=AsyncMock(return_value=True)) as publish,
        ):
            response = await get_async_task_status("task-1", user_id="u1")

        self.assertEqual(response.status, "error")
        self.assertIn("未生成可下载报告", response.error)
        self.assertIn("后台任务未完成", publish.await_args.kwargs["content"])

    async def test_returns_pending_when_remote_thread_has_no_runs(self) -> None:
        """尚未物化运行记录时，前端应继续轮询而不是视为失败。"""
        client = SimpleNamespace(runs=SimpleNamespace(list=AsyncMock(return_value=[])))

        with patch("api.async_tasks.get_client", return_value=client):
            response = await get_async_task_status("task-1", user_id="u1")

        self.assertEqual(response.status, "pending")
        self.assertFalse(response.done)

    async def test_run_limit_error_is_not_delivered_as_a_successful_report(self) -> None:
        """框架的调用限额终态必须显示为可理解的失败，而非原始内部错误。"""
        client = SimpleNamespace(
            runs=SimpleNamespace(list=AsyncMock(return_value=[{"status": "success"}])),
            threads=SimpleNamespace(
                get_state=AsyncMock(return_value=SimpleNamespace(values={
                    "messages": [{
                        "role": "assistant",
                        "content": "Tool call limit reached: run limit exceeded (11/10 calls).",
                    }],
                }))
            ),
        )

        with (
            patch("api.async_tasks.get_client", return_value=client),
            patch(
                "api.async_tasks.agent_loader.publish_async_task_result",
                new=AsyncMock(return_value=True),
            ) as publish,
        ):
            response = await get_async_task_status("task-1", user_id="u1")

        self.assertEqual(response.status, "error")
        self.assertIn("执行限额", response.error)
        self.assertNotIn("Tool call", response.result)
        self.assertIn("后台任务未完成", response.result)
        self.assertNotIn("Tool call", publish.await_args.kwargs["content"])

    def test_extracts_agent_protocol_task_id_from_tool_result(self) -> None:
        """主聊天流应能从异步工具返回的嵌套文本中登记任务归属。"""
        task_id = "12fd2b03-f2c1-4b80-a8ca-9cb91bc43ccd"
        self.assertEqual(
            extract_async_task_id({"result": [f"任务已创建：{task_id}"]}),
            task_id,
        )

    def test_removes_internal_artifact_references_from_task_report(self) -> None:
        """图表链接由响应字段提供，报告正文不能泄露资源标识或沙箱路径。"""
        content = _sanitize_task_content(
            "结论：采购金额集中。\n• **资源 ID**： abcdef0123456789abcdef0123456789\n"
            "• **静态 HTML 文件**： /mnt/procurement_chart.html\n建议：复核大额订单。"
        )
        self.assertEqual(content, "结论：采购金额集中。\n建议：复核大额订单。")

    def test_extracts_only_standard_sandbox_report_path(self) -> None:
        """下载登记只能接受子 Agent 输出的标准沙箱报告路径。"""
        self.assertEqual(_extract_report_path(f"结论\nREPORT_PATH: {REPORT_PATH}"), REPORT_PATH)
        self.assertIsNone(_extract_report_path("REPORT_PATH: /tmp/report.md"))

    def test_report_negation_does_not_turn_chart_only_request_into_report_request(self) -> None:
        from api.async_tasks import _task_requests_report

        self.assertFalse(_task_requests_report({
            "messages": [{"role": "human", "content": "只画图，不要生成报告"}],
        }))
        self.assertTrue(_task_requests_report({
            "messages": [{"role": "human", "content": "生成采购分析报告"}],
        }))

class AsyncTaskDeliveryTests(unittest.IsolatedAsyncioTestCase):
    """验证 AgentLoader 向主 checkpoint 投递异步结果的边界。"""

    async def test_publishes_main_message_once_for_repeated_polling(self) -> None:
        """固定消息 ID 应让重复轮询保持幂等。"""
        task_id = "12fd2b03-f2c1-4b80-a8ca-9cb91bc43ccd"
        store = SimpleNamespace(
            aget=AsyncMock(
                return_value=SimpleNamespace(
                    value={"user_id": "u1", "username": "张三", "thread_id": "thread-1"}
                )
            )
        )
        agent = SimpleNamespace(aupdate_state=AsyncMock())
        loader = AgentLoader()
        loader._initialized = True
        loader._store = store
        loader._history_reader = SimpleNamespace(
            get_state=AsyncMock(
                side_effect=[
                    SimpleNamespace(values={"messages": []}, next=(), interrupts=()),
                    SimpleNamespace(values={"messages": [SimpleNamespace(id=f"async-task-result:{task_id}")]}, next=(), interrupts=()),
                ]
            )
        )

        with (
            patch.object(loader, "get_agent_for_user", new=AsyncMock(return_value=agent)),
            patch.object(loader, "save_session", new=AsyncMock()),
        ):
            delivered = await loader.publish_async_task_result(
                task_id,
                content="图表已生成。",
                artifact={"type": "chart_artifact", "artifact_id": "a" * 32, "mime_type": "text/html"},
                report={"report_id": "b" * 32, "label": "下载采购分析报告"},
            )
            delivered_again = await loader.publish_async_task_result(
                task_id,
                content="图表已生成。",
                artifact={"type": "chart_artifact", "artifact_id": "a" * 32, "mime_type": "text/html"},
                report={"report_id": "b" * 32, "label": "下载采购分析报告"},
            )

        self.assertTrue(delivered)
        self.assertTrue(delivered_again)
        self.assertEqual(agent.aupdate_state.await_count, 1)
        message = agent.aupdate_state.await_args.args[1]["messages"][0]
        self.assertEqual(message.id, f"async-task-result:{task_id}")
        self.assertEqual(message.additional_kwargs["source"], "main")
        self.assertEqual(message.content[1]["artifact_id"], "a" * 32)
        self.assertEqual(message.content[2]["report_id"], "b" * 32)


class NonStreamingAsyncTaskBindingTests(unittest.IsolatedAsyncioTestCase):
    """``/chat`` 必须绑定与 ``/chat/stream`` 相同的任务 ID。"""

    async def test_binds_task_id_from_final_tool_message(self) -> None:
        """已完成的 ``ainvoke`` 结果必须登记其异步任务归属。"""
        task_id = "12fd2b03-f2c1-4b80-a8ca-9cb91bc43ccd"
        result = {
            "messages": [
                SimpleNamespace(name="start_async_task", content=f"task_id: {task_id}"),
                SimpleNamespace(type="ai", content="任务已提交。"),
            ]
        }

        with patch("api.chat.agent_loader.bind_async_task", new=AsyncMock()) as bind:
            from api.chat import _bind_async_tasks_from_result

            await _bind_async_tasks_from_result(
                result,
                user_id="u1",
                username="张三",
                thread_id="thread-1",
            )

        bind.assert_awaited_once_with(
            task_id,
            user_id="u1",
            username="张三",
            thread_id="thread-1",
        )
