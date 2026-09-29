"""
会话历史 HTTP 接口。

会话正文始终从 LangGraph 的 PostgreSQL checkpoint 恢复；
会话索引保存在PostgreSQL Store 的 ``("sessions", user_id)`` 命名空间。
这样同一用户可看到自己的历史会话，后续接入登录后只需传入真实 ``user_id``，无需改变消息存储结构。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Query

from agent.schema import (
    DeleteSessionResponse,
    Message,
    ReportArtifact,
    Session,
    SessionListResponse,
    SessionMessagesResponse,
    Visualization,
)
from api.agent_loader import agent_loader
from api.async_tasks import extract_async_task_id
from api.message_utils import (
    content_to_text,
    extract_sandbox_report,
    extract_visualization,
    serialize_interrupt,
)


router = APIRouter(prefix="/history", tags=["history"])
DEFAULT_SESSION_TITLE = "新对话"


def _message_value(message: Any, name: str, default: Any = None) -> Any:
    """
    从 LangChain 消息对象或 checkpoint 字典中读取指定字段。
    """
    # checkpoint 迁移或不同 LangGraph 版本可能产生对象或字典，两种格式必须兼容。
    return message.get(name, default) if isinstance(message, dict) else getattr(message, name, default)


def _message_role(message: Any) -> str:
    """
    将 LangChain 的消息类型标准化为前端使用的角色名称。
    """
    # LangChain 使用 human/ai，前端和 schema 统一使用 user/assistant。
    role = _message_value(message, "role") or _message_value(message, "type")
    return {"human": "user", "ai": "assistant"}.get(str(role), str(role or "assistant"))


def _task_subagent_name(args: Any) -> str | None:
    """从 task 工具参数中读取隔离子 Agent 的原名。"""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return None
    if not isinstance(args, dict):
        return None
    name = args.get("subagent_type")
    return str(name) if name else None


def _task_description(args: Any) -> str:
    """从委派参数中提取给用户展示的任务摘要，而不暴露完整参数。"""
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            return ""
    if not isinstance(args, dict):
        return ""
    description = args.get("description")
    return str(description).strip() if description else ""


def _report_for_user(content: Any, user_id: str) -> ReportArtifact | None:
    """将 checkpoint 的报告标识转换为当前用户可下载的受控 URL。"""
    report = extract_sandbox_report(content)
    if report is None:
        return None
    report_id = report["report_id"]
    return ReportArtifact(
        report_id=report_id,
        label=report["label"],
        download_src=f"/analysis/reports/{report_id}?user_id={user_id}",
    )


def serialize_messages(messages: list[Any], user_id: str = "u1") -> list[Message]:
    """
    将 checkpoint 消息转换为与 SSE 流式过程一致的前端展示消息。

    助手消息中的工具调用先转为“执行中”占位消息；随后到达的工具结果按
    ``tool_call_id`` 回填该占位消息，避免历史记录和实时展示的顺序不一致。
    """
    serialized: list[Message] = []
    tool_messages: dict[str, Message] = {}
    now = datetime.now(timezone.utc)
    completed_tasks = {
        str(_message_value(message, "id", "")).removeprefix("async-task-result:")
        for message in messages
        if str(_message_value(message, "id", "")).startswith("async-task-result:")
    }

    for index, message in enumerate(messages):
        role = _message_role(message)
        message_content = _message_value(message, "content", "")
        content = content_to_text(message_content)
        if role == "assistant":
            # AIMessage 可同时携带文本和工具调用，必须先保留文本的原始顺序。
            additional_kwargs = _message_value(message, "additional_kwargs", {}) or {}
            report = _report_for_user(message_content, user_id)
            if content or report:
                source = str(additional_kwargs.get("source", "main"))
                # 子 Agent 自身的文本是内部执行记录，用户历史只展示主 Agent 交付。
                if source != "main":
                    continue
                visualization = extract_visualization(message_content)
                serialized.append(
                    Message(
                        id=str(_message_value(message, "id", None) or f"message-{index}"),
                        role="assistant",
                        content=content,
                        source=source,
                        async_task_id=additional_kwargs.get("async_task_id"),
                        visualization=Visualization(**visualization) if visualization else None,
                        report=report,
                        created_at=now,
                    )
                )
            for call_index, tool_call in enumerate(_message_value(message, "tool_calls", []) or []):
                call = tool_call if isinstance(tool_call, dict) else {}
                call_id = str(call.get("id") or f"tool-{index}-{call_index}")
                tool_name = str(call.get("name", "MCP 工具"))
                is_delegation = tool_name in {"task", "start_async_task"}
                subagent_name = _task_subagent_name(call.get("args")) if is_delegation else None
                # task 是主 Agent 与隔离子 Agent 的边界。
                # 历史中将其保留为委派记录，而不是伪装成普通 MCP 工具调用。
                tool_message = Message(
                    id=call_id,
                    role="delegation" if is_delegation else "tool",
                    tool_name=tool_name,
                    # 子任务仅暴露面向用户的任务摘要；普通工具仍保留实际参数。
                    content=_task_description(call.get("args")) if is_delegation else "",
                    args="" if is_delegation else str(call.get("args", "")),
                    text="",
                    tool_status="calling",
                    source=subagent_name or ("subagent" if is_delegation else "main"),
                    created_at=now,
                )
                serialized.append(tool_message)
                tool_messages[call_id] = tool_message
        elif role == "tool":
            # 工具结果通常带 tool_call_id；缺失时仍展示为独立的工具结果。
            call_id = str(_message_value(message, "tool_call_id", ""))
            tool_message = tool_messages.get(call_id)
            tool_status = "error" if _message_value(message, "status") == "error" else "done"
            visualization = extract_visualization(_message_value(message, "content", ""))
            if tool_message is None:
                tool_message = Message(
                    id=call_id or f"message-{index}",
                    role="tool",
                    tool_name=str(_message_value(message, "name", "MCP 工具")),
                    text=content,
                    tool_status=tool_status,
                    source="main",
                    visualization=visualization,
                    created_at=now,
                )
                serialized.append(tool_message)
            else:
                if (
                    tool_message.role == "delegation"
                    and tool_message.tool_name == "start_async_task"
                    and tool_status != "error"
                ):
                    # 保留远程 ID，使刷新后的前端可以继续轮询尚未投递的结果。
                    task_id = extract_async_task_id(message_content)
                    tool_message.async_task_id = task_id
                    if task_id in completed_tasks:
                        tool_message.tool_status = "done"
                    continue
                tool_message.tool_status = tool_status
                if tool_status == "error":
                    tool_message.text = content
                if tool_message.role == "delegation" and tool_message.tool_name == "task":
                    # 同步子 Agent 只回传最终报告；异步任务的最终交付由
                    # 主会话中的 source=main 消息承载。
                    tool_message.text = content
                    tool_message.visualization = Visualization(**visualization) if visualization else None
                elif tool_message.role != "delegation":
                    tool_message.text = content
                    tool_message.visualization = Visualization(**visualization) if visualization else None
        elif role == "user":
            additional_kwargs = _message_value(message, "additional_kwargs", {}) or {}
            serialized.append(Message(id=f"message-{index}", role="user", content=content, created_at=now))
    return serialized


def _session_from_index(item: dict[str, Any], message_count: int) -> Session:
    """
    将 PostgreSQL Store 中的会话索引转换为接口响应模型。

    空会话没有 checkpoint 消息，但仍需出现在侧边栏，供用户在输入首条消息前识别和切换当前会话。
    """
    return Session(
        thread_id=item["thread_id"],
        title=item.get("title") or DEFAULT_SESSION_TITLE,
        created_at=datetime.fromisoformat(item["created_at"]),
        updated_at=datetime.fromisoformat(item["updated_at"]),
        message_count=message_count,
    )


@router.post("", response_model=Session)
async def create_session(user_id: str = Query("u1", min_length=1)) -> Session:
    """
    创建一条尚未发送消息的会话，并立即返回给侧边栏。
    """
    thread_id = str(uuid4())
    await agent_loader.save_session(user_id, thread_id, DEFAULT_SESSION_TITLE)
    session = await agent_loader.get_session(user_id, thread_id)
    assert session is not None
    return _session_from_index(session, message_count=0)


@router.get("", response_model=SessionListResponse)
async def list_sessions(user_id: str = Query("u1", min_length=1)) -> SessionListResponse:
    """
    获取当前用户已登记的会话列表。
    """
    indexed_sessions = await agent_loader.list_sessions(user_id)

    # 索引只保存列表元数据；消息数由 DeepAgents 重建的框架状态决定。
    # 空会话也必须返回，否则首次打开时刚创建的“新对话”会被错误隐藏。
    sessions: list[Session] = []
    for item in indexed_sessions:
        messages = await agent_loader.get_thread_messages(item["thread_id"])
        sessions.append(_session_from_index(item, message_count=len(serialize_messages(messages))))
    return SessionListResponse(sessions=sessions)


@router.get("/{thread_id}/messages", response_model=SessionMessagesResponse)
async def get_session_messages(thread_id: str, user_id: str = Query("u1", min_length=1)) -> SessionMessagesResponse:
    """
    恢复当前用户指定会话的全部可展示消息。
    """
    # 先检查会话索引，避免仅凭 thread_id 读取到其他用户的 checkpoint。
    if await agent_loader.get_session(user_id, thread_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    state = await agent_loader.get_thread_state(thread_id)
    interrupts = state.interrupts
    return SessionMessagesResponse(
        thread_id=thread_id,
        messages=serialize_messages(list(state.values.get("messages", [])), user_id=user_id),
        interrupt=serialize_interrupt(interrupts[0], thread_id) if interrupts else None,
    )


@router.delete("/{thread_id}", response_model=DeleteSessionResponse)
async def delete_session(thread_id: str, user_id: str = Query("u1", min_length=1)) -> DeleteSessionResponse:
    """
    删除当前用户的一条会话及其 checkpoint 数据。
    """
    # 与读取接口使用同一所有权校验，防止跨用户删除已知的 thread_id。
    if await agent_loader.get_session(user_id, thread_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在或无权访问")
    await agent_loader.delete_session(user_id, thread_id)
    return DeleteSessionResponse(success=True)
