"""查询远程异步任务，并将终态结果投递到所属主会话。"""

from __future__ import annotations

import os
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from langgraph_sdk import get_client

from agent.schema import AsyncTaskStatusResponse
from api.agent_loader import agent_loader
from api.message_utils import content_to_text, extract_visualization


router = APIRouter()

ASYNC_AGENT_PROTOCOL_URL = os.getenv(
    "MYAGENT_ASYNC_AGENT_PROTOCOL_URL",
    os.getenv("MYAGENT_ASYNC_CHART_URL", "http://127.0.0.1:18082"),
)
TERMINAL_RUN_STATUSES = {"success", "error", "interrupted", "cancelled", "timeout"}
TASK_ID_PATTERN = re.compile(
    r"\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_RUN_LIMIT_ERROR_PATTERN = re.compile(
    r"(?:tool call limit reached|model call limits exceeded)",
    re.IGNORECASE,
)
_INTERNAL_ARTIFACT_LINE_PATTERN = re.compile(
    r"(?im)^[^\r\n]*(?:资源(?:\s|\*|_)*ID|静态(?:\s|\*|_)*HTML(?:\s|\*|_)*文件)[^\r\n]*(?:\r?\n|$)",
)
REPORT_REQUEST_PATTERN = re.compile(r"(?:报告|报表|分析报告|markdown)|\breport\b", re.IGNORECASE)
REPORT_REQUEST_NEGATION_PATTERN = re.compile(
    r"(?:不要|无需|不需要|不用|不生成|不提供|不输出)[^。！？\n]{0,12}"
    r"(?:报告|报表|分析报告|markdown)|(?:no|without|不要)\s+\breport",
    re.IGNORECASE,
)
REPORT_PATH_LINE_PATTERN = re.compile(
    r"(?im)^\s*REPORT_PATH\s*:\s*`?(/analysis/report_\d{8}_\d{6}\.md)`?\s*$"
)


def _get_attr(value: Any, key: str, default: Any = None) -> Any:
    """兼容 LangGraph SDK 返回的字典和对象属性访问。"""
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def extract_async_task_id(value: Any) -> str | None:
    """从异步任务工具结果中提取 Agent Protocol 分配的任务线程 ID。"""
    if isinstance(value, str):
        match = TASK_ID_PATTERN.search(value)
        return match.group(0) if match else None
    if isinstance(value, list):
        for item in value:
            task_id = extract_async_task_id(item)
            if task_id:
                return task_id
    if isinstance(value, dict):
        for item in value.values():
            task_id = extract_async_task_id(item)
            if task_id:
                return task_id
    return None


def _message_role(message: Any) -> str:
    """将 SDK 消息角色归一化为页面使用的角色名称。"""
    role = _get_attr(message, "role")
    if role:
        return {"human": "user", "ai": "assistant"}.get(str(role), str(role))
    message_type = str(_get_attr(message, "type", type(message).__name__)).lower()
    if "human" in message_type:
        return "user"
    if "tool" in message_type:
        return "tool"
    return "assistant"


def _extract_task_output(values: Any) -> tuple[str, dict[str, str] | None]:
    """提取最终助手文本及最后一个可展示的图表 artifact。"""
    if not isinstance(values, dict):
        return "", None
    messages = values.get("messages")
    if not isinstance(messages, list):
        return "", None

    content = ""
    visualization: dict[str, str] | None = None
    for message in reversed(messages):
        message_content = _get_attr(message, "content", "")
        if visualization is None:
            visualization = extract_visualization(message_content)
        if not content and _message_role(message) == "assistant":
            content = content_to_text(message_content).strip()
        if content and visualization:
            break
    return content, visualization


def _task_requests_report(values: Any) -> bool:
    """根据异步任务的原始用户请求判断是否应要求报告文件。"""
    if not isinstance(values, dict) or not isinstance(values.get("messages"), list):
        return False
    for message in values["messages"]:
        if _message_role(message) != "user":
            continue
        content = content_to_text(_get_attr(message, "content", ""))
        if REPORT_REQUEST_NEGATION_PATTERN.search(content):
            continue
        if REPORT_REQUEST_PATTERN.search(content):
            return True
    return False


def _extract_error(run: Any, state: Any) -> str | None:
    """从运行元数据或线程任务中提取可供用户查看的失败原因。"""
    metadata = _get_attr(run, "metadata", {}) or {}
    if isinstance(metadata, dict):
        for key in ("error", "exception", "message"):
            if metadata.get(key):
                return str(metadata[key])
    for task in _get_attr(state, "tasks", []) or []:
        error = _get_attr(task, "error")
        if error:
            return str(error)
    return None


def _run_limit_error(content: str) -> str | None:
    """将框架限额错误转换为不暴露内部运行细节的业务说明。"""
    if _RUN_LIMIT_ERROR_PATTERN.search(content):
        return "分析任务超过本次执行限额，未能形成完整结论。请重试或缩小分析范围。"
    return None


def _extract_report_path(content: str) -> str | None:
    """读取采购分析器按交付协议写入沙箱的报告路径。"""
    match = REPORT_PATH_LINE_PATTERN.search(content)
    return match.group(1) if match else None


def _sanitize_task_content(content: str) -> str:
    """移除系统登记报告和图表时不应展示的内部标识。"""
    content = REPORT_PATH_LINE_PATTERN.sub("", content)
    return _INTERNAL_ARTIFACT_LINE_PATTERN.sub("", content).strip()


@router.get("/async-tasks/{task_id}", response_model=AsyncTaskStatusResponse)
async def get_async_task_status(
    task_id: str, user_id: str = Query(..., min_length=1),
) -> AsyncTaskStatusResponse:
    """返回任务状态；终态结果写入主会话并回传任务卡片所需的 artifact。"""
    binding = await agent_loader.get_async_task_binding(task_id)
    if binding is None or binding.user_id != user_id:
        raise HTTPException(status_code=404, detail="任务不存在或无权访问")
    await agent_loader.require_session(user_id, binding.thread_id)
    client = get_client(url=ASYNC_AGENT_PROTOCOL_URL)
    try:
        runs = await client.runs.list(task_id, limit=10)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="无法查询异步子 Agent 任务，请稍后重试",
        ) from exc

    if not runs:
        return AsyncTaskStatusResponse(task_id=task_id, status="pending", done=False)

    latest_run = runs[0]
    status = str(_get_attr(latest_run, "status", "unknown")).lower()
    status = {"failed": "error", "canceled": "cancelled", "timed_out": "timeout"}.get(status, status)
    is_terminal = status in TERMINAL_RUN_STATUSES
    if not is_terminal:
        return AsyncTaskStatusResponse(
            task_id=task_id, status=status, done=False,
            run_id=_get_attr(latest_run, "run_id"),
        )
    state = None
    content = ""
    visualization = None
    report_requested = False
    report_path = None
    try:
        state = await client.threads.get_state(task_id)
        values = _get_attr(state, "values", {})
        content, visualization = _extract_task_output(values)
        report_requested = _task_requests_report(values)
        report_path = _extract_report_path(content)
        content = _sanitize_task_content(content)
    except Exception as exc:
        # run 成功不代表已读到结果；失败必须可重试，不能写入占位成功消息。
        raise HTTPException(status_code=502, detail="无法读取异步任务结果，请稍后重试") from exc

    delivered = False
    error = None
    if is_terminal:
        artifact = None
        if visualization is not None and visualization.get("artifact_id"):
            artifact = {
                "type": "chart_artifact",
                "artifact_id": visualization["artifact_id"],
                "mime_type": visualization.get("mime_type", "text/html"),
            }
        elif visualization is not None:
            artifact = {
                "type": "image", "src": visualization["src"],
                "mime_type": visualization.get("mime_type", "image/png"),
            }
        limit_error = _run_limit_error(content)
        report = None
        if status == "success" and limit_error:
            # Agent Protocol 会将中间件的 end 视为成功终态；不能把限额错误伪装成报告。
            status = "error"
            error = limit_error
            main_message = (
                "图表已生成，但本次分析未能形成完整结论。"
                "请重试或缩小分析范围后再获取报告。"
                if visualization is not None
                else f"后台任务未完成：{error}"
            )
        elif status == "success":
            if report_requested and report_path is None:
                status = "error"
                error = "采购分析未生成可下载报告，请重试。"
                main_message = f"后台任务未完成：{error}"
            elif report_requested:
                try:
                    report = await agent_loader.register_sandbox_report(task_id, report_path)
                except Exception as exc:
                    raise HTTPException(
                        status_code=502,
                        detail="无法登记采购分析报告，请稍后重试",
                    ) from exc
                if report is None:
                    status = "error"
                    error = "采购分析报告不可用，请重试。"
                    main_message = f"后台任务未完成：{error}"
                else:
                    main_message = "图表和采购分析报告已生成。" if visualization else "采购分析报告已生成。"
            elif visualization is None and not content:
                # 通用异步任务允许返回普通文本；只有完全没有正文和交付物时，
                # 才能判定为远端成功状态下的空结果，避免伪造成功交付。
                raise HTTPException(status_code=502, detail="异步任务未返回可交付结果，请稍后重试")
            else:
                # 图表-only 请求不应因为没有报告而失败。
                main_message = "图表已生成。" if visualization else content
        else:
            error = _extract_error(latest_run, state) or {
                "timeout": "后台任务超时。", "cancelled": "后台任务已取消。",
                "interrupted": "后台任务已中断。",
            }.get(status, "后台任务未能完成。")
            main_message = f"后台任务未完成：{error}"
        try:
            delivered = await agent_loader.publish_async_task_result(
                task_id,
                content=main_message,
                artifact=artifact,
                report=report,
            )
        except Exception as exc:
            raise HTTPException(
                status_code=502,
                detail="无法将异步任务结果写入主会话，请稍后重试",
            ) from exc

    return AsyncTaskStatusResponse(
        task_id=task_id,
        status=status,
        done=is_terminal,
        delivered=delivered,
        result=main_message if is_terminal else None,
        visualization=visualization if is_terminal else None,
        report=(
            {
                "report_id": report["report_id"],
                "label": report["label"],
                "download_src": f"/analysis/reports/{report['report_id']}?user_id={user_id}",
            }
            if is_terminal and report is not None
            else None
        ),
        error=error,
        run_id=_get_attr(latest_run, "run_id"),
        updated_at=str(_get_attr(latest_run, "updated_at", "")) or None,
    )
