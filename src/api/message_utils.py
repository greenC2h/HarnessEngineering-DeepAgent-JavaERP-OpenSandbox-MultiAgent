"""
对话接口共用的消息内容与会话标题转换工具。

实时 SSE 和 checkpoint 历史都可能接收到 LangChain 的结构化内容；在此处统一
转换规则，保证两条路径展示相同文本，并避免标题截断规则逐渐出现差异。
"""

from __future__ import annotations

import json
import mimetypes
import re
from typing import Any

from services.visualization_artifacts import (
    ARTIFACT_ID_PATTERN as ARTIFACT_ID_VALUE_PATTERN,
    get_visualization_path,
    visualization_src,
)


_IMAGE_URL_PATTERN = re.compile(
    r"^https?://\S+\.(?:png|jpe?g|gif|webp|svg)(?:[?#].*)?$",
    re.IGNORECASE,
)
_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\((https?://[^)]+)\)")
_ARTIFACT_REFERENCE_PATTERN = re.compile(
    r"(?:artifact_id|artifact-id|资源标识)(?:[\s*_`])*[:：]\s*`?([0-9a-f]{32})`?",
    re.IGNORECASE,
)


def content_to_text(content: Any) -> str:
    """
    将 LangChain 文本或多模态内容块转换为可直接展示的纯文本。
    """
    if isinstance(content, str):
        parsed = _parse_json_content(content)
        if (
            isinstance(parsed, dict)
            and parsed.get("type") == "chart_artifact"
            and parsed.get("message")
        ):
            return str(parsed["message"])
        return content
    if isinstance(content, list):
        text_parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                text_parts.append(item)
            elif isinstance(item, dict):
                # 文本块使用 text；非文本多模态块没有可直接展示的文本则忽略。
                text = item.get("text")
                if text is not None:
                    text_parts.append(str(text))
        return "".join(text_parts)
    return "" if content is None else str(content)


def _parse_json_content(content: Any) -> Any:
    """解析工具可能以 JSON 字符串封装的结构化内容。"""
    if not isinstance(content, str):
        return content
    stripped = content.strip()
    if not stripped or stripped[0] not in "[{":
        return content
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return content


def _image_source(data: Any, mime_type: Any) -> dict[str, str] | None:
    """将 MCP 图片块转换为前端可用的图片资源。"""
    if not isinstance(data, str) or not data.strip():
        return None
    source = data.strip()
    normalized_mime = str(mime_type or "image/png")
    if source.startswith("data:") or source.startswith("http://") or source.startswith("https://"):
        return {
            "kind": "image",
            "src": source,
            "mime_type": normalized_mime,
        }
    return {
        "kind": "image",
        "src": f"data:{normalized_mime};base64,{source}",
        "mime_type": normalized_mime,
    }


def _artifact_visualization(
    artifact_id: str,
    declared_mime_type: str = "text/html",
) -> dict[str, str]:
    """
    将持久化资源标识转换为前端资源描述，并优先采用实际文件类型。

    旧 checkpoint 的最终文本可能只保留 ``artifact_id``，甚至把旧 PNG
    误标为 HTML。文件仍存在时以扩展名为准，避免静态截图被显示为交互图表。
    文件已过期时保留声明类型的入口，让资源路由返回统一的过期占位图。
    """
    source = visualization_src(artifact_id)
    path = get_visualization_path(artifact_id)
    mime_type = declared_mime_type
    if path is not None:
        mime_type = mimetypes.guess_type(path.name)[0] or declared_mime_type

    if mime_type == "text/html":
        return {
            "kind": "link",
            "src": source,
            "artifact_id": artifact_id,
            "mime_type": mime_type,
            "label": "打开 HTML 图表",
            "download_src": f"{source}?download=1",
        }
    return {
        "kind": "image",
        "src": source,
        "artifact_id": artifact_id,
        "mime_type": mime_type,
    }


def _find_visualization(content: Any, depth: int = 0) -> dict[str, str] | None:
    """递归查找 MCP 文本、图片块或资源块中的可视化内容。"""
    if depth > 5:
        return None
    content = _parse_json_content(content)
    if isinstance(content, list):
        for item in content:
            visualization = _find_visualization(item, depth + 1)
            if visualization:
                return visualization
        return None
    if isinstance(content, dict):
        block_type = str(content.get("type", ""))
        if block_type == "chart_artifact":
            artifact_id = str(content.get("artifact_id", ""))
            mime_type = str(content.get("mime_type") or "text/html")
            if ARTIFACT_ID_VALUE_PATTERN.fullmatch(artifact_id):
                return _artifact_visualization(artifact_id, mime_type)
        if block_type == "image":
            return _image_source(
                content.get("data")
                or content.get("src")
                or content.get("base64"),
                content.get("mimeType") or content.get("mime_type"),
            )
        if block_type == "resource":
            visualization = _find_visualization(content.get("resource"), depth + 1)
            if visualization:
                return visualization
        if content.get("text") is not None:
            visualization = _find_visualization(content["text"], depth + 1)
            if visualization:
                return visualization
        for key in ("url", "uri", "image_url", "content"):
            if content.get(key) is not None:
                visualization = _find_visualization(content[key], depth + 1)
                if visualization:
                    return visualization
        return None
    if not isinstance(content, str):
        return None

    stripped = content.strip()
    if stripped.startswith("data:image/"):
        return {"kind": "image", "src": stripped, "mime_type": stripped.split(";", 1)[0][5:]}
    if _IMAGE_URL_PATTERN.match(stripped):
        return {"kind": "image", "src": stripped, "mime_type": "image/*"}
    markdown_match = _MARKDOWN_IMAGE_PATTERN.search(stripped)
    if markdown_match:
        return {"kind": "image", "src": markdown_match.group(1), "mime_type": "image/*"}
    artifact_match = _ARTIFACT_REFERENCE_PATTERN.search(stripped)
    if artifact_match:
        artifact_id = artifact_match.group(1).lower()
        return _artifact_visualization(artifact_id)
    return None


def extract_visualization(content: Any) -> dict[str, str] | None:
    """
    从 MCP 工具结果中提取安全传输给前端的可视化资源描述。

    只识别图片 URL/data URL 和持久化图表资源；原始 HTML 或远程 HTML URL
    不进入前端，避免工具结果绕过本地图表资源边界。普通 JSON、Markdown 或
    工具日志仍按原文本展示。
    """
    return _find_visualization(content)


def _find_sandbox_report(content: Any, depth: int = 0) -> dict[str, str] | None:
    """从主会话消息中提取报告元数据，绝不向前端暴露沙箱路径。"""
    if depth > 5:
        return None
    content = _parse_json_content(content)
    if isinstance(content, list):
        for item in content:
            report = _find_sandbox_report(item, depth + 1)
            if report:
                return report
        return None
    if not isinstance(content, dict):
        return None
    if content.get("type") == "sandbox_report":
        report_id = str(content.get("report_id", ""))
        if re.fullmatch(r"[0-9a-f]{32}", report_id):
            return {
                "report_id": report_id,
                "label": str(content.get("label") or "下载采购分析报告"),
            }
    for value in content.values():
        report = _find_sandbox_report(value, depth + 1)
        if report:
            return report
    return None


def extract_sandbox_report(content: Any) -> dict[str, str] | None:
    """返回会话消息中的受控报告标识，供 API 组装下载入口。"""
    return _find_sandbox_report(content)


def make_session_title(content: str, max_length: int = 30) -> str:
    """
    从首条用户消息生成长度稳定的会话标题。
    """
    # 空白消息不应显示为空标题；省略号只在内容确实被截断时添加。
    normalized_content = content.strip()
    if not normalized_content:
        return "新会话"
    suffix = "..." if len(normalized_content) > max_length else ""
    return f"{normalized_content[:max_length]}{suffix}"


def serialize_interrupt(interrupt: Any, thread_id: str) -> dict[str, Any]:
    """
    将 checkpoint 或流式中断转换为统一协议，保留恢复所需的中断 ID。
    """
    value = getattr(interrupt, "value", interrupt)
    interrupt_id = getattr(interrupt, "id", None)
    if isinstance(value, dict) and "value" in value and "id" in value:
        interrupt_id, value = value["id"], value["value"]
    value = value if isinstance(value, dict) else {}
    event: dict[str, Any] = {"type": "interrupt", "thread_id": thread_id}
    if interrupt_id:
        event["interrupt_id"] = str(interrupt_id)
    if "action_requests" in value:
        event.update(interrupt_type="hitl_approval", action_requests=value["action_requests"])
        if "review_configs" in value:
            event["review_configs"] = value["review_configs"]
    elif value.get("type") == "information_request":
        event.update(
            interrupt_type="information_request",
            information_needed=value.get("information_needed", ""),
            context=value.get("context", ""),
        )
    else:
        event.update(interrupt_type="unknown", interrupt_value=content_to_text(value))
    return event
