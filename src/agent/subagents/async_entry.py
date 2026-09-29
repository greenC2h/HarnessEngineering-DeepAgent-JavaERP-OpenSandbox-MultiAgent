"""为 Agent Protocol 构造已注册的异步子 Agent 图。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend
from langgraph_sdk.runtime import ServerRuntime
from opensandbox.config.connection_sync import ConnectionConfigSync
from opensandbox.sync import SandboxSync

from agent.subagents.async_registry import get_async_subagent_registration
from agent.config import (
    ASYNC_SUBAGENT_MODEL_RUN_LIMIT,
    ASYNC_SUBAGENT_TOOL_RUN_LIMIT,
    MAIN_MODEL,
    OPEN_SANDBOX_API_KEY,
    OPEN_SANDBOX_DEFAULT_TIMEOUT_SECONDS,
    OPEN_SANDBOX_HOST,
    OPEN_SANDBOX_PORT,
    SKILLS_ROOT,
    SUMMARY_MODEL,
)
from agent.backends.skill_sync import SandboxSkillSynchronizer
from agent.middlewares.agent_protection import build_agent_protection_middleware
from agent.middlewares.skills_sync import SandboxSkillsMiddleware
from agent.backends.open_sandbox import OpenSandboxBackend
from agent.backends.sandbox_proxy import SandboxBackendProxy
from agent.subagents.loader import load_subagent


async def _load_subagent_config(name: str) -> dict[str, Any]:
    """加载指定异步子 Agent 的 YAML 配置和独立工具。"""
    registration = get_async_subagent_registration(name)
    return load_subagent(
        registration.config_path,
        await registration.tool_loader(),
    )


def build_async_subagent_graph(name: str, sandbox_backend: SandboxBackendProxy) -> Any:
    """
    用相同后端类型构建执行和只读图，保持节点、工具及状态拓扑一致。
    """
    registration = get_async_subagent_registration(name)
    subagent_config = _SUBAGENT_CONFIGS[name]

    backend = CompositeBackend(
        default=sandbox_backend,
        routes={},
    )
    skill_synchronizer = SandboxSkillSynchronizer(
        SKILLS_ROOT,
        Path(__file__).parent.parent / "memory" / "AGENTS.md",
    )
    return create_deep_agent(
        model=MAIN_MODEL,
        system_prompt=subagent_config["system_prompt"],
        tools=subagent_config["tools"],
        skills=subagent_config.get("skills", []),
        backend=backend,
        middleware=[
            # 远程图共享用户沙箱，必须先同步本地技能，才能读取 YAML 指向的技能目录。
            SandboxSkillsMiddleware(
                backend=backend,
                sources=subagent_config.get("skills", []),
                synchronizer=skill_synchronizer,
            ),
            *build_agent_protection_middleware(
                backend=backend,
                summary_model=SUMMARY_MODEL,
                model_run_limit=ASYNC_SUBAGENT_MODEL_RUN_LIMIT,
                tool_run_limit=ASYNC_SUBAGENT_TOOL_RUN_LIMIT,
            ),
        ],
        # YAML 中声明的订单写操作审批必须传入图工厂；仅保留在配置中不会生效。
        interrupt_on=subagent_config.get("interrupt_on"),
        checkpointer=None,
        name=registration.graph_id,
    )


@asynccontextmanager
async def procurement_analyst_agent(runtime: ServerRuntime) -> AsyncIterator[Any]:
    """
    只在执行上下文连接沙箱，并在图的生命周期结束后释放客户端。
    """
    proxy = SandboxBackendProxy()
    try:
        execution = runtime.execution_runtime
        if execution is not None:
            context = execution.context or {}
            sandbox_id = context.get("sandbox_id") if isinstance(context, dict) else getattr(context, "sandbox_id", None)
            if not sandbox_id:
                raise RuntimeError("异步任务缺少 sandbox_id 上下文")
            if not OPEN_SANDBOX_API_KEY:
                raise RuntimeError("未配置 OPEN_SANDBOX_API_KEY，异步子 Agent 无法连接沙箱")
            connection = ConnectionConfigSync(
                api_key=OPEN_SANDBOX_API_KEY,
                domain=f"{OPEN_SANDBOX_HOST}:{OPEN_SANDBOX_PORT}",
            )
            task = asyncio.create_task(asyncio.to_thread(
                SandboxSync.connect, str(sandbox_id), connection_config=connection,
            ))
            try:
                sandbox = await asyncio.shield(task)
            except asyncio.CancelledError:
                # 同步 SDK 可能在取消后仍完成；必须接住结果并关闭已创建的客户端。
                try:
                    sandbox = await task
                except Exception:
                    pass
                else:
                    await asyncio.to_thread(sandbox.close)
                raise
            try:
                backend = OpenSandboxBackend(sandbox, OPEN_SANDBOX_DEFAULT_TIMEOUT_SECONDS)
            except BaseException:
                await asyncio.to_thread(sandbox.close)
                raise
            proxy.replace_backend(backend)
        yield build_async_subagent_graph("procurement_analyst", proxy)
    finally:
        await asyncio.to_thread(proxy.close)


try:
    # Agent Protocol 在已有事件循环中调用图工厂；MCP 工具必须在模块导入时
    # 预加载，避免工厂内嵌套 asyncio.run() 使每个后台任务立刻失败。
    _SUBAGENT_CONFIGS = {
        "procurement_analyst": asyncio.run(_load_subagent_config("procurement_analyst")),
    }
except RuntimeError as exc:
    raise RuntimeError(
        "无法加载异步子 Agent procurement_analyst 的工具。"
        "请确认其依赖的 MCP 服务可访问后再启动 Agent Protocol 服务。"
    ) from exc
