"""集中定义可由 Agent Protocol 托管的异步子 Agent。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepagents import AsyncSubAgent

from agent.tools.chart_tools import create_chart_tools
from agent.tools.mcp_client import load_chart_mcp_tools, load_mcp_tools


AsyncToolLoader = Callable[[], Awaitable[list[Any]]]


@dataclass(frozen=True)
class AsyncSubagentRegistration:
    """描述一个可独立启动的异步子 Agent 的固定配置。"""

    name: str
    graph_id: str
    description: str
    config_path: Path
    tool_loader: AsyncToolLoader
    launch_instruction: str


async def _load_procurement_analyst_tools() -> list[Any]:
    """加载异步采购分析、图表与报告所需的只读业务工具。"""
    common_tools, order_tools = await load_mcp_tools()
    chart_tools = create_chart_tools(await load_chart_mcp_tools())
    return [*chart_tools, *order_tools, *common_tools]


ASYNC_SUBAGENTS: dict[str, AsyncSubagentRegistration] = {
    "procurement_analyst": AsyncSubagentRegistration(
        name="procurement_analyst",
        graph_id="procurement_analyst_async",
        description=(
            "异步采购分析器。负责只读订单检索、外部信息检索、采购分析、交互式 "
            "HTML 图表和沙箱 Markdown 报告。"
        ),
        config_path=Path(__file__).parent / "configs" / "procurement_analyst.yaml",
        tool_loader=_load_procurement_analyst_tools,
        launch_instruction=(
            "处理需要采购分析、市场调研、趋势、对比或图表的 ERP 任务时，"
            "必须使用 `start_async_task` 启动 `procurement_analyst`。不要同步委派；"
            "子 Agent 负责查询、搜索、分析、图表和报告；用户要求报告时，必须由它写入沙箱并返回"
            "标准 REPORT_PATH。任务 ID 仅供系统轮询，不得向用户展示。完成后的图表和报告会自动写回当前会话。"
        ),
    ),
}


def get_async_subagent_registration(name: str) -> AsyncSubagentRegistration:
    """按名称返回异步子 Agent 注册信息，未知名称直接失败。"""
    try:
        return ASYNC_SUBAGENTS[name]
    except KeyError as exc:
        raise ValueError(f"未知异步子 Agent: {name}") from exc


def get_async_subagent_specs(protocol_url: str) -> list[AsyncSubAgent]:
    """返回主 Agent 注册远程任务工具所需的最小子 Agent 描述。"""
    return [
        {
            "name": registration.name,
            "description": registration.description,
            "graph_id": registration.graph_id,
            "url": protocol_url,
        }
        for registration in ASYNC_SUBAGENTS.values()
    ]


def get_async_subagent_instructions() -> str:
    """生成主 Agent 需要遵守的异步任务委派与用户可见性规则。"""
    instructions = "\n".join(
        f"- {registration.launch_instruction}"
        for registration in ASYNC_SUBAGENTS.values()
    )
    return f"""
## 异步采购分析任务

{instructions}
""".strip()
