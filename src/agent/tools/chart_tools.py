"""将图表 MCP 工具压缩为图表子 Agent 的按需接口。"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx
from langchain_core.tools import tool

from services.visualization_artifacts import save_visualization


_HTML_PREFIXES = ("<!doctype html", "<html", "<svg")
_HTML_URL_PATTERN = re.compile(r"https?://\S+\.html(?:[?#].*)?$", re.IGNORECASE)


def _chart_type_from_tool_name(tool_name: str) -> str | None:
    """将 generate_* 工具名转换为稳定的 chart_type。"""
    if not tool_name.startswith("generate_"):
        return None
    chart_type = tool_name.removeprefix("generate_")
    if chart_type.endswith("_chart"):
        chart_type = chart_type.removesuffix("_chart")
    return chart_type or None


def _schema_from_tool(chart_tool: Any) -> dict[str, Any]:
    """读取 MCP StructuredTool 的 JSON Schema，兼容 Pydantic v1/v2。"""
    schema_model = getattr(chart_tool, "args_schema", None)
    if schema_model is None:
        return {}
    if isinstance(schema_model, dict):
        return schema_model
    model_json_schema = getattr(schema_model, "model_json_schema", None)
    if callable(model_json_schema):
        return model_json_schema()
    schema = getattr(schema_model, "schema", None)
    if callable(schema):
        return schema()
    return {}


def _resolve_schema(schema: dict[str, Any], root_schema: dict[str, Any]) -> dict[str, Any]:
    """解析最小示例生成所需的本地 JSON Schema 引用。"""
    reference = schema.get("$ref")
    if reference and reference.startswith("#/"):
        resolved: Any = root_schema
        for part in reference[2:].split("/"):
            resolved = resolved.get(part, {}) if isinstance(resolved, dict) else {}
        return resolved if isinstance(resolved, dict) else {}
    for key in ("anyOf", "oneOf"):
        alternatives = schema.get(key)
        if isinstance(alternatives, list):
            for alternative in alternatives:
                if isinstance(alternative, dict) and alternative.get("type") != "null":
                    return _resolve_schema(alternative, root_schema)
    return schema


def _example_value(
    schema: dict[str, Any],
    root_schema: dict[str, Any],
    property_name: str = "",
) -> Any:
    """根据 MCP Schema 生成一个只包含必要字段的最小示例。"""
    schema = _resolve_schema(schema, root_schema)
    if "default" in schema:
        return schema["default"]
    if "const" in schema:
        return schema["const"]
    enum = schema.get("enum")
    if isinstance(enum, list) and enum:
        return enum[0]

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), "string")

    if schema_type == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            return {}
        required = schema.get("required") or list(properties)[:1]
        return {
            name: _example_value(properties[name], root_schema, name)
            for name in required
            if name in properties and isinstance(properties[name], dict)
        }
    if schema_type == "array":
        items = schema.get("items")
        if isinstance(items, dict):
            return [_example_value(items, root_schema, property_name)]
        return []
    if schema_type == "integer":
        return 1
    if schema_type == "number":
        return 1
    if schema_type == "boolean":
        return False
    if schema_type == "string":
        lowered_name = property_name.lower()
        if lowered_name == "format":
            return "html"
        if lowered_name in {"time", "date"}:
            return "2025-01"
        return "示例"
    return None


def _compact_description(description: str) -> str:
    """将底层工具说明压缩成图表目录中的单行场景描述。"""
    normalized = " ".join(str(description or "").split())
    first_sentence = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)[0]
    return first_sentence[:180] or "生成该类型的可视化图表"


def _build_chart_tool_map(chart_mcp_tools: list[Any]) -> dict[str, Any]:
    """建立 chart_type 到 MCP 生成工具的映射，并拒绝重复类型。"""
    chart_tool_map: dict[str, Any] = {}
    for chart_tool in chart_mcp_tools:
        chart_type = _chart_type_from_tool_name(str(getattr(chart_tool, "name", "")))
        if chart_type is None:
            continue
        if chart_type in chart_tool_map:
            raise ValueError(f"图表类型重复: {chart_type}")
        chart_tool_map[chart_type] = chart_tool
    if not chart_tool_map:
        raise ValueError("图表 MCP Server 未提供 generate_* 工具")
    return chart_tool_map


def _request_html_config(chart_config: dict[str, Any]) -> dict[str, Any]:
    """复制图表参数并请求 MCP 返回可临时保存的 HTML。"""
    config = dict(chart_config)
    input_config = config.get("input")
    if isinstance(input_config, dict):
        config["input"] = {**input_config, "format": "html"}
    else:
        config["format"] = "html"
    return config


async def _download_html(url: str) -> str:
    """下载 MCP 返回的 HTML 资源，避免把远程临时 URL 暴露给 Agent。"""
    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        response = await client.get(url)
        response.raise_for_status()
    return response.text


def _strip_code_fence(value: str) -> str:
    """去除 MCP 文本结果可能附带的 Markdown 代码围栏。"""
    match = re.fullmatch(r"```(?:html)?\s*(.*?)```", value.strip(), re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else value.strip()


def _find_html_payload(value: Any, depth: int = 0) -> tuple[str, str] | None:
    """从 MCP 结果中找到 HTML 或 HTML URL，不把原始 URL向上返回。"""
    if depth > 6:
        return None
    if isinstance(value, tuple) and value:
        return _find_html_payload(value[0], depth + 1)
    if isinstance(value, list):
        for item in value:
            payload = _find_html_payload(item, depth + 1)
            if payload:
                return payload
        return None
    if isinstance(value, dict):
        for key in ("text", "content", "resource", "result", "resultObj", "html", "uri"):
            if key in value:
                payload = _find_html_payload(value[key], depth + 1)
                if payload:
                    return payload
        return None
    if not isinstance(value, str):
        return None

    text = _strip_code_fence(value)
    if text.startswith("{") or text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if parsed is not None:
            payload = _find_html_payload(parsed, depth + 1)
            if payload:
                return payload
    lowered = text.lower()
    if lowered.startswith(_HTML_PREFIXES):
        return "html", text
    if _HTML_URL_PATTERN.fullmatch(text):
        return "html-url", text
    return None


async def _html_from_result(result: Any) -> str:
    """把底层 MCP 结果统一转换为可暂存的 HTML 文本。"""
    payload = _find_html_payload(result)
    if payload is None:
        raise RuntimeError("图表 MCP 未返回 HTML 或 HTML URL")

    payload_type, payload_value = payload
    return await _download_html(payload_value) if payload_type == "html-url" else payload_value


def create_chart_tools(chart_mcp_tools: list[Any]) -> list[Any]:
    """
    创建图表子 Agent 使用的两个按需工具。

    Args:
        chart_mcp_tools: 从图表 MCP Server 发现的 StructuredTool 列表。

    Returns:
        只包含 ``get_chart_spec`` 和 ``generate_visualization`` 的工具列表。
    """
    chart_tool_map = _build_chart_tool_map(chart_mcp_tools)
    catalog = "\n".join(
        f"- {chart_type}: {_compact_description(getattr(chart_tool, 'description', ''))}"
        for chart_type, chart_tool in sorted(chart_tool_map.items())
    )
    available_types = ", ".join(sorted(chart_tool_map))

    @tool
    def get_chart_spec(chart_type: str) -> str:
        """按图表类型返回底层 MCP 的真实 JSON Schema 和最小示例。"""
        chart_tool = chart_tool_map.get(chart_type)
        if chart_tool is None:
            return json.dumps(
                {
                    "error": f"未知图表类型: {chart_type}",
                    "available_types": sorted(chart_tool_map),
                },
                ensure_ascii=False,
            )
        schema = _schema_from_tool(chart_tool)
        return json.dumps(
            {
                "chart_type": chart_type,
                "tool_name": chart_tool.name,
                "description": getattr(chart_tool, "description", ""),
                "input_schema": schema,
                "minimum_example": _example_value(schema, schema),
            },
            ensure_ascii=False,
        )

    get_chart_spec.description = (
        "按需获取一种图表的真实 MCP 输入 Schema 和最小示例。"
        f"可用 chart_type: {available_types}。"
    )

    @tool
    async def generate_visualization(
        chart_type: str,
        chart_config: dict[str, Any],
    ) -> Any:
        """调用图表 MCP，将 HTML 结果暂存为图表资源并返回文本记录。"""
        chart_tool = chart_tool_map.get(chart_type)
        if chart_tool is None:
            return json.dumps(
                {
                    "error": f"未知图表类型: {chart_type}",
                    "available_types": sorted(chart_tool_map),
                },
                ensure_ascii=False,
            )
        result = await chart_tool.ainvoke(_request_html_config(chart_config))
        html = await _html_from_result(result)
        artifact = save_visualization(html.encode("utf-8"), "text/html")
        return json.dumps(
            {
                "type": "chart_artifact",
                "status": "generated",
                "chart_type": chart_type,
                "artifact_id": artifact["artifact_id"],
                "mime_type": artifact["mime_type"],
                "message": "图表已生成，HTML 图表已暂存。",
            },
            ensure_ascii=False,
        )

    generate_visualization.description = (
        "生成图表、地图或关系图。先在需要时调用 get_chart_spec 获取真实字段，"
        "再传入完整 chart_config。工具会把 MCP 的 HTML 结果暂存为本地资源，"
        "返回 chart_artifact 文本记录，不会向 Agent 返回 html_url 或原始 HTML。"
        "图表目录如下：\n"
        f"{catalog}"
    )
    return [get_chart_spec, generate_visualization]
