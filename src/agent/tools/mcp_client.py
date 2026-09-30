"""按业务来源加载 MCP 工具并返回固定分组。"""

from __future__ import annotations

from copy import copy
import logging
import os
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient


logger = logging.getLogger(__name__)


MCP_SERVER_CONFIG_COMMON = {
    "bing-search": {
        "url": (
            "https://mcp.api-inference.modelscope.net/"
            f"{os.getenv('MODELSCOPE_BING_SEARCH_MCP_TOKEN', '')}/mcp"
        ),
        "transport": "streamable_http",
    }
}

MCP_SERVER_CONFIG_ORDER = {
    "erp-api": {
        "url": (
            f"http://{os.getenv('MYAGENT_MCP_HOST', '127.0.0.1')}:"
            f"{os.getenv('MYAGENT_MCP_PORT', '18081')}"
            f"{os.getenv('MYAGENT_MCP_PATH', '/mcp')}"
        ),
        "transport": "streamable_http",
    }
}

MCP_SERVER_CONFIG_CHART = {
    "charts-mcp": {
        "url": (
            "https://mcp.api-inference.modelscope.net/"
            f"{os.getenv('MODELSCOPE_CHARTS_MCP_TOKEN', '')}/mcp"
        ),
        "transport": "streamable_http",
    }
}

# 子 Agent 依赖项目定义的工具名，不能直接依赖外部 MCP 的供应商命名。
# 当前搜索 MCP 提供 bing_search，因此在工具发现边界统一为 web_search。
COMMON_TOOL_NAME_ALIASES = {"bing_search": "web_search"}


def _normalize_common_tool_names(tools: list[Any]) -> list[Any]:
    """将公共 MCP 工具名称适配为项目稳定的 Agent 工具契约。"""
    normalized_tools: list[Any] = []
    normalized_names: set[str] = set()

    for tool in tools:
        original_name = str(getattr(tool, "name", ""))
        normalized_name = COMMON_TOOL_NAME_ALIASES.get(original_name, original_name)

        if normalized_name in normalized_names:
            raise RuntimeError(f"公共 MCP 工具名称冲突: {normalized_name}")
        normalized_names.add(normalized_name)

        if normalized_name == original_name:
            normalized_tools.append(tool)
            continue

        # MCP 返回的 StructuredTool 是 Pydantic 模型；复制后改名会保留 schema 和回调。
        if hasattr(tool, "model_copy"):
            normalized_tools.append(tool.model_copy(update={"name": normalized_name}))
            continue

        # 测试替身和兼容工具不一定继承 Pydantic；复制避免改写调用方持有的对象。
        renamed_tool = copy(tool)
        setattr(renamed_tool, "name", normalized_name)
        normalized_tools.append(renamed_tool)

    return normalized_tools


async def _load_tools(
    server_config: dict[str, dict[str, str]],
    group_name: str,
) -> list[Any]:
    """
    连接一组 MCP Server 并合并其工具。

    Args:
        server_config: 当前工具组对应的 MCP Server 配置。
        group_name: 用于日志和异常信息的工具组名称。

    Returns:
        当前工具组内全部已发现的 MCP 工具。

    Raises:
        RuntimeError: MCP Server 连接或工具加载失败。
    """
    client = MultiServerMCPClient(server_config)
    tools_in_group: list[Any] = []

    for server_name in server_config:
        try:
            # MCP 连接和工具发现均为网络异步操作。
            server_tools = await client.get_tools(server_name=server_name)
        except Exception as exc:
            logger.exception("加载 %s MCP Server 工具失败: %s", group_name, server_name)
            raise RuntimeError(
                f"无法加载 {group_name} MCP Server 的工具: {server_name}"
            ) from exc

        tools_in_group.extend(server_tools)
        logger.info(
            "已从 %s MCP Server %s 加载 %d 个工具",
            group_name,
            server_name,
            len(server_tools),
        )

    return tools_in_group


async def load_mcp_tools(
    common_server_config: dict[str, dict[str, str]] | None = None,
    order_server_config: dict[str, dict[str, str]] | None = None,
) -> tuple[list[Any], list[Any]]:
    """
    加载公共工具和 Java ERP 工具，并按来源分别返回。

    Args:
        common_server_config: 可选的公共 MCP Server 配置。
        order_server_config: 可选的 Java ERP MCP Server 配置。

    Returns:
        ``(common_tools, order_tools)`` 二元组。前者是已有的公共工具，
        后者是 Java ERP MCP Server 暴露的采购业务工具。

    Raises:
        RuntimeError: 任一 MCP Server 连接或工具加载失败。
    """
    # 显式允许空配置，便于测试或按部署环境禁用某一类外部工具。
    common_config = (
        MCP_SERVER_CONFIG_COMMON
        if common_server_config is None
        else common_server_config
    )
    order_config = (
        MCP_SERVER_CONFIG_ORDER
        if order_server_config is None
        else order_server_config
    )
    common_tools = _normalize_common_tool_names(
        await _load_tools(common_config, "公共")
    )
    order_tools = await _load_tools(order_config, "采购")
    logger.info(
        "MCP 工具加载完成: 公共工具 %d 个，采购工具 %d 个",
        len(common_tools),
        len(order_tools),
    )
    return common_tools, order_tools


async def load_chart_mcp_tools(
    chart_server_config: dict[str, dict[str, str]] | None = None,
) -> list[Any]:
    """
    加载图表子 Agent 使用的 ModelScope MCP 工具。

    Args:
        chart_server_config: 可选的图表 MCP Server 配置，主要用于测试或部署覆盖。

    Returns:
        ModelScope 图表 MCP Server 暴露的全部工具。

    Raises:
        RuntimeError: 图表 MCP Server 连接或工具发现失败。
    """
    config = (
        MCP_SERVER_CONFIG_CHART
        if chart_server_config is None
        else chart_server_config
    )
    chart_tools = await _load_tools(config, "图表")
    logger.info("图表 MCP 工具加载完成: %d 个", len(chart_tools))
    return chart_tools
