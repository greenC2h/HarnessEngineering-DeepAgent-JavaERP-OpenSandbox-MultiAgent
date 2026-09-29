"""通用的同步子 Agent 配置加载器。"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

import yaml


REQUIRED_CONFIG_KEYS = {"name", "description", "system_prompt", "tools"}
OPTIONAL_SUBAGENT_KEYS = {"model", "skills", "middleware", "interrupt_on", "permissions"}


def load_subagent(
    config_path: str | Path,
    available_tools: Iterable[Any],
    *,
    local_tools: Iterable[Any] = (),
) -> dict[str, Any]:
    """
    同步读取一个 YAML 子 Agent 配置，并绑定配置中声明的工具。

    Args:
        config_path: 子 Agent YAML 配置路径。
        available_tools: 当前运行时可提供的 MCP 或其他工具。
        local_tools: 不来自 MCP、但允许由配置声明的本地工具。

    Returns:
        可直接传给 ``create_deep_agent(subagents=...)`` 的配置字典。

    Raises:
        ValueError: 配置结构无效、工具名称重复或声明的工具不可用。
    """
    path = Path(config_path)
    with path.open(encoding="utf-8") as config_file:
        config = yaml.safe_load(config_file)

    if not isinstance(config, dict) or not REQUIRED_CONFIG_KEYS.issubset(config):
        raise ValueError(f"子 Agent 配置无效: {path}")

    configured_names = config["tools"]
    if not isinstance(configured_names, list) or not all(
        isinstance(name, str) and name for name in configured_names
    ):
        raise ValueError(f"子 Agent 工具配置无效: {path}")
    if len(configured_names) != len(set(configured_names)):
        raise ValueError(f"子 Agent 工具配置重复: {path}")

    tool_map: dict[str, Any] = {}
    for tool in [*available_tools, *local_tools]:
        tool_name = str(getattr(tool, "name", ""))
        if not tool_name:
            continue
        if tool_name in tool_map:
            raise ValueError(f"子 Agent 工具名称重复: {tool_name}")
        tool_map[tool_name] = tool

    missing_tools = set(configured_names) - set(tool_map)
    if missing_tools:
        names = ", ".join(sorted(missing_tools))
        raise ValueError(f"子 Agent 缺少配置工具: {names}")

    subagent = {
        "name": config["name"],
        "description": config["description"],
        "system_prompt": config["system_prompt"],
        "tools": [tool_map[name] for name in configured_names],
    }
    for key in OPTIONAL_SUBAGENT_KEYS:
        if key in config and config[key] is not None:
            subagent[key] = config[key]
    return subagent
