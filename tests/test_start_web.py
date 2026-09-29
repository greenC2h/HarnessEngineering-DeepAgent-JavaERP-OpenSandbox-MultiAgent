"""验证统一启动脚本在端口冲突时不会启动错误的子服务。"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from start_web import (
    async_agent_protocol_command,
    build_python_env,
    ensure_port_available,
    java_backend_command,
    terminate_processes,
    wait_for_http,
)


class EnsurePortAvailableTests(unittest.TestCase):
    """覆盖启动前端口检查的核心行为。"""

    def test_raises_when_port_is_already_listening(self) -> None:
        """端口被占用时应在启动子进程前提供明确错误。"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            occupied_port = listener.getsockname()[1]

            with self.assertRaisesRegex(RuntimeError, str(occupied_port)):
                ensure_port_available("127.0.0.1", occupied_port, "测试服务")

    @patch("start_web.socket.socket")
    def test_reports_system_port_reservation_separately(self, socket_mock) -> None:
        """系统拒绝绑定时不能误报为旧进程占用端口。"""
        probe = socket_mock.return_value.__enter__.return_value
        probe.bind.side_effect = PermissionError(13, "Permission denied")

        with self.assertRaisesRegex(RuntimeError, "系统拒绝绑定"):
            ensure_port_available("127.0.0.1", 4500, "Vue")

    @patch("start_web.urlopen")
    def test_http_406_counts_as_service_ready(self, urlopen_mock) -> None:
        """MCP 端点普通 GET 返回 406 时仍应视为服务已监听。"""
        urlopen_mock.side_effect = HTTPError(
            "http://127.0.0.1:18081/mcp",
            406,
            "Not Acceptable",
            None,
            None,
        )

        process = MagicMock()
        process.poll.return_value = None
        self.assertTrue(wait_for_http("http://127.0.0.1:18081/mcp", process))

    def test_async_agent_command_uses_the_local_agent_protocol_runtime(self) -> None:
        """异步子 Agent 图必须由本地 LangGraph CLI 使用项目配置启动。"""
        command = async_agent_protocol_command()

        self.assertIn("langgraph_cli", command)
        self.assertIn("langgraph.json", command)
        self.assertIn("--no-browser", command)
        self.assertEqual(
            build_python_env()["MYAGENT_ASYNC_AGENT_PROTOCOL_URL"],
            "http://127.0.0.1:18082",
        )
        self.assertEqual(build_python_env()["LOG_COLOR"], "false")

    def test_java_backend_command_uses_maven_project_and_configured_port(self) -> None:
        """Java 后端命令必须从迁移后的 Maven 项目启动并传入服务端口。"""
        command = java_backend_command()
        command_text = " ".join(command)

        self.assertIn("spring-boot:run", command)
        self.assertIn("java-backend", command_text)
        self.assertIn("pom.xml", command_text)
        self.assertIn(
            "-Dspring-boot.run.arguments=--server.address=127.0.0.1 --server.port=18080",
            command,
        )
        self.assertEqual(
            build_python_env()["JAVA_API_BASE_URL"],
            "http://127.0.0.1:18080/api",
        )

    @unittest.skipUnless(os.name == "nt", "Windows 进程树清理")
    def test_stop_terminates_a_descendant_listener(self) -> None:
        """
        停止父进程后，孙进程占用的端口也必须释放。
        """
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        child_code = (
            "import socket,time; s=socket.socket(); "
            f"s.bind(('127.0.0.1',{port})); s.listen(); time.sleep(60)"
        )
        parent_code = (
            "import subprocess,sys,time; "
            f"subprocess.Popen([sys.executable,'-c',{child_code!r}]); time.sleep(60)"
        )
        process = subprocess.Popen([sys.executable, "-c", parent_code])
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                with socket.socket() as probe:
                    if probe.connect_ex(("127.0.0.1", port)) == 0:
                        break
                time.sleep(0.05)
            else:
                self.fail("受控子进程未开始监听")
            terminate_processes([process])
            ensure_port_available("127.0.0.1", port, "受控测试服务")
        finally:
            terminate_processes([process])
