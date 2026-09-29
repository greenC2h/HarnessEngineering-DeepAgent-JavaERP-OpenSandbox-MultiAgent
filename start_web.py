"""启动 MotoParts Agent ERP 的 Java、MCP、FastAPI 和 Vue 服务。"""

from __future__ import annotations

import os
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Sequence
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
JAVA_BACKEND_DIR = PROJECT_ROOT / "java-backend"
PYTHON_EXE = PROJECT_ROOT / "myagent" / "Scripts" / "python.exe"

BACKEND_HOST = os.environ.get("MYAGENT_BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = int(os.environ.get("MYAGENT_BACKEND_PORT", "18000"))
FRONTEND_HOST = os.environ.get("MYAGENT_FRONTEND_HOST", "127.0.0.1")
FRONTEND_PORT = int(os.environ.get("MYAGENT_FRONTEND_PORT", "19000"))
JAVA_BACKEND_HOST = os.environ.get("MYAGENT_JAVA_BACKEND_HOST", "127.0.0.1")
JAVA_BACKEND_PORT = int(os.environ.get("MYAGENT_JAVA_BACKEND_PORT", "18080"))
JAVA_MAVEN_COMMAND = os.environ.get(
    "MYAGENT_JAVA_MAVEN_COMMAND",
    "mvn.cmd" if os.name == "nt" else "mvn",
)
MCP_HOST = os.environ.get("MYAGENT_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.environ.get("MYAGENT_MCP_PORT", "18081"))
MCP_PATH = os.environ.get("MYAGENT_MCP_PATH", "/mcp")
ASYNC_AGENT_HOST = os.environ.get(
    "MYAGENT_ASYNC_AGENT_HOST",
    os.environ.get("MYAGENT_ASYNC_CHART_HOST", "127.0.0.1"),
)
ASYNC_AGENT_PORT = int(
    os.environ.get(
        "MYAGENT_ASYNC_AGENT_PORT",
        os.environ.get("MYAGENT_ASYNC_CHART_PORT", "18082"),
    )
)

# Vite 输出包含 Unicode 箭头；Windows PowerShell 的默认 GBK 输出会导致
# 日志转发线程崩溃，因此由启动器统一使用 UTF-8 转发子进程日志。
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


def build_python_env() -> dict[str, str]:
    """构建后端和前端进程共用的环境变量。"""
    environment = os.environ.copy()
    node_dir = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs"
    if node_dir.exists():
        environment["PATH"] = os.pathsep.join(
            (str(node_dir), environment.get("PATH", ""))
        )
    existing_pythonpath = environment.get("PYTHONPATH")
    pythonpath_entries = [str(SRC_DIR)]
    if existing_pythonpath:
        pythonpath_entries.append(existing_pythonpath)
    environment["PYTHONPATH"] = os.pathsep.join(pythonpath_entries)
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    # langgraph-cli 的 ConsoleRenderer 在 Windows 上启用颜色时依赖 colorama；
    # 服务日志不需要颜色，显式关闭以保持 myagent 环境的最小依赖集。
    environment["LOG_COLOR"] = "false"
    async_agent_url = f"http://{ASYNC_AGENT_HOST}:{ASYNC_AGENT_PORT}"
    environment["MYAGENT_ASYNC_AGENT_PROTOCOL_URL"] = async_agent_url
    # 保留旧变量，避免已有本地启动脚本在迁移期间失效。
    environment["MYAGENT_ASYNC_CHART_URL"] = async_agent_url
    environment.setdefault(
        "JAVA_API_BASE_URL",
        f"http://{JAVA_BACKEND_HOST}:{JAVA_BACKEND_PORT}/api",
    )
    return environment


def stream_process_output(process: subprocess.Popen[str], name: str) -> None:
    """读取子进程输出，并添加服务名称前缀后转发。"""
    if process.stdout is None:
        return
    for line in process.stdout:
        print(f"[{name}] {line.rstrip()}", flush=True)


def start_process(
    name: str,
    command: Sequence[str],
    cwd: Path,
    environment: dict[str, str],
) -> subprocess.Popen[str]:
    """启动一个服务，并在线程中转发其输出。"""
    print(f"[{name}] Starting: {' '.join(command)}", flush=True)
    process = subprocess.Popen(
        list(command),
        cwd=str(cwd),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    output_thread = threading.Thread(
        target=stream_process_output,
        args=(process, name),
        daemon=True,
    )
    output_thread.start()
    return process


def wait_for_http(url: str, process: subprocess.Popen[str], timeout: float = 60) -> bool:
    """等待服务响应，或在服务进程退出时结束等待。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urlopen(url, timeout=2) as response:
                if 200 <= response.status < 500:
                    return True
        except HTTPError as exc:
            # Streamable HTTP 的 MCP 端点对普通 GET 可能返回 406，
            # 但这已经证明服务成功监听并能处理请求。
            if 200 <= exc.code < 500:
                return True
        except (URLError, OSError):
            time.sleep(0.5)
    return False


def ensure_port_available(host: str, port: int, service_name: str) -> None:
    """确认服务目标端口可绑定。

    启动前检查可避免旧进程占用端口时，健康检查误命中旧服务而把新服务误判为启动成功。
    调用者需在创建任何子进程前执行此检查。
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            # Windows 上 SO_REUSEADDR 会允许探测 socket 复用已监听端口，
            # 进而造成端口冲突检查假阴性，因此这里必须保持默认值。
            probe.bind((host, port))
    except OSError as exc:
        if isinstance(exc, PermissionError) or exc.errno in {13, 10013}:
            raise RuntimeError(
                f"{service_name} 端口 {host}:{port} 被系统拒绝绑定。"
                "该端口可能处于 Windows 保留范围，请设置对应服务的端口变量后重试。"
            ) from exc
        raise RuntimeError(
            f"{service_name} 端口 {host}:{port} 已被占用。"
            "请先结束旧的 start_web.py、uvicorn 或 Vite 进程，"
            "或设置对应服务的端口变量使用其他端口。"
        ) from exc


def terminate_processes(processes: Sequence[subprocess.Popen[str]]) -> None:
    """
    停止本启动器拥有的服务进程树，并等待直接子进程退出。

    Windows 的 npm 和 Python 启动器会创建后代进程；只终止包装进程会让
    端口继续被占用。按记录的 PID 清理树，避免影响机器上的其他同名服务。
    """
    for process in reversed(processes):
        if process.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=15,
                )
            else:
                process.terminate()
    for process in reversed(processes):
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


def backend_command() -> list[str]:
    """构建后端启动命令，并保持 Windows Selector 事件循环。"""
    runner = (
        "import asyncio; "
        "asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy()); "
        "import uvicorn; "
        f"uvicorn.run('api.chat:app', host='{BACKEND_HOST}', port={BACKEND_PORT}, loop='none')"
    )
    return [str(PYTHON_EXE), "-c", runner]


def java_backend_command() -> list[str]:
    """构建 Java Spring Boot 后端的 Maven 启动命令。"""
    return [
        JAVA_MAVEN_COMMAND,
        "-f",
        str(JAVA_BACKEND_DIR / "pom.xml"),
        "spring-boot:run",
        f"-Dspring-boot.run.arguments=--server.address={JAVA_BACKEND_HOST} --server.port={JAVA_BACKEND_PORT}",
    ]


def mcp_command() -> list[str]:
    """构建 Java ERP MCP 适配服务的启动命令。"""
    return [str(PYTHON_EXE), "-m", "mcp_server.server_main"]


def async_agent_protocol_command() -> list[str]:
    """构建承载已注册异步子 Agent 的 Agent Protocol 启动命令。"""
    return [
        str(PYTHON_EXE),
        "-m",
        "langgraph_cli",
        "dev",
        "--config",
        "langgraph.json",
        "--host",
        ASYNC_AGENT_HOST,
        "--port",
        str(ASYNC_AGENT_PORT),
        "--n-jobs-per-worker",
        "10",
        "--allow-blocking",
        "--no-browser",
        "--no-reload",
    ]


def main() -> int:
    """启动 Java、MCP、Python 后端和前端，直到收到中断信号。"""
    if not PYTHON_EXE.exists():
        print(f"Python environment not found: {PYTHON_EXE}", file=sys.stderr)
        return 1
    if not (FRONTEND_DIR / "package.json").exists():
        print(f"Frontend project not found: {FRONTEND_DIR}", file=sys.stderr)
        return 1
    if not (JAVA_BACKEND_DIR / "pom.xml").exists():
        print(f"Java backend project not found: {JAVA_BACKEND_DIR}", file=sys.stderr)
        return 1
    if shutil.which(JAVA_MAVEN_COMMAND) is None and not Path(JAVA_MAVEN_COMMAND).exists():
        print(
            f"Maven command not found: {JAVA_MAVEN_COMMAND}. "
            "请安装 Maven，或设置 MYAGENT_JAVA_MAVEN_COMMAND。",
            file=sys.stderr,
        )
        return 1

    try:
        ensure_port_available(BACKEND_HOST, BACKEND_PORT, "FastAPI")
        ensure_port_available(FRONTEND_HOST, FRONTEND_PORT, "Vue")
        ensure_port_available(JAVA_BACKEND_HOST, JAVA_BACKEND_PORT, "Java ERP 后端")
        ensure_port_available(MCP_HOST, MCP_PORT, "Java ERP MCP")
        ensure_port_available(ASYNC_AGENT_HOST, ASYNC_AGENT_PORT, "异步子 Agent Protocol")
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1

    environment = build_python_env()
    processes: list[subprocess.Popen[str]] = []

    def handle_signal(signum: int, _frame: object) -> None:
        print(f"\nReceived signal {signum}; stopping services...", flush=True)
        terminate_processes(processes)
        raise SystemExit(0)

    signal.signal(signal.SIGINT, handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_signal)

    try:
        java_backend = start_process(
            "Java ERP Backend",
            java_backend_command(),
            JAVA_BACKEND_DIR,
            environment,
        )
        processes.append(java_backend)
        java_backend_url = f"http://{JAVA_BACKEND_HOST}:{JAVA_BACKEND_PORT}/"
        print(f"Waiting for Java ERP Backend: {java_backend_url}", flush=True)
        if not wait_for_http(java_backend_url, java_backend, timeout=120):
            print("Java ERP Backend failed to become ready.", file=sys.stderr)
            return 1

        mcp_server = start_process(
            "Java ERP MCP",
            mcp_command(),
            PROJECT_ROOT,
            environment,
        )
        processes.append(mcp_server)
        mcp_url = f"http://{MCP_HOST}:{MCP_PORT}{MCP_PATH}"
        print(f"Waiting for Java ERP MCP: {mcp_url}", flush=True)
        if not wait_for_http(mcp_url, mcp_server):
            print("Java ERP MCP failed to become ready.", file=sys.stderr)
            return 1

        async_agent_protocol = start_process(
            "Async Agent Protocol",
            async_agent_protocol_command(),
            PROJECT_ROOT,
            environment,
        )
        processes.append(async_agent_protocol)
        async_agent_url = f"http://{ASYNC_AGENT_HOST}:{ASYNC_AGENT_PORT}/ok"
        print(f"Waiting for Async Agent Protocol: {async_agent_url}", flush=True)
        if not wait_for_http(async_agent_url, async_agent_protocol, timeout=120):
            print("Async Agent Protocol failed to become ready.", file=sys.stderr)
            return 1

        backend = start_process(
            "Backend",
            backend_command(),
            PROJECT_ROOT,
            environment,
        )
        processes.append(backend)
        backend_url = f"http://{BACKEND_HOST}:{BACKEND_PORT}/"
        print(f"Waiting for FastAPI: {backend_url}", flush=True)
        if not wait_for_http(backend_url, backend):
            print("FastAPI failed to become ready.", file=sys.stderr)
            return 1

        frontend = start_process(
            "Frontend",
            [
                str(Path(os.environ.get("ProgramFiles", r"C:\\Program Files")) / "nodejs" / "npm.cmd"),
                "run",
                "dev",
                "--",
                "--host",
                FRONTEND_HOST,
                "--port",
                str(FRONTEND_PORT),
                "--strictPort",
            ],
            FRONTEND_DIR,
            environment,
        )
        processes.append(frontend)
        frontend_url = f"http://{FRONTEND_HOST}:{FRONTEND_PORT}/"
        print(f"Waiting for Vue: {frontend_url}", flush=True)
        if not wait_for_http(frontend_url, frontend):
            print("Vue failed to become ready.", file=sys.stderr)
            return 1

        print(f"Services started. Open: {frontend_url}", flush=True)
        print("Press Ctrl+C to stop all services.", flush=True)
        while all(process.poll() is None for process in processes):
            time.sleep(1)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        terminate_processes(processes)


if __name__ == "__main__":
    raise SystemExit(main())
