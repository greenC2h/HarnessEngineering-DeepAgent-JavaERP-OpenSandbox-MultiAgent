"""采购 Agent 的最小对话 HTTP 接口。"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
import re
import uuid
from contextlib import aclosing, asynccontextmanager, suppress
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import APIRouter, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from langgraph.types import Command

from agent.schema import ChatRequest, ChatResponse, ProcurementContext, ResumeChatRequest
from api.agent_loader import agent_loader
from api.async_tasks import extract_async_task_id, router as async_tasks_router
from api.auth import router as auth_router
from api.history import router as history_router
from api.message_utils import (
    content_to_text, extract_visualization, make_session_title,
    serialize_interrupt as _serialize_interrupt,
)
from services.visualization_artifacts import (
    EXPIRED_VISUALIZATION_SVG,
    get_visualization_path,
    run_visualization_cleanup,
)


logger = logging.getLogger(__name__)

router = APIRouter()
PROJECT_DIR = Path(__file__).resolve().parents[2]
VUE_DIST_DIR = PROJECT_DIR / "frontend" / "dist"
LEGACY_WEB_DIR = Path(__file__).resolve().parent.parent / "web"
# 本地开发使用 Vite，部署或沿用 uvicorn 启动方式时优先服务 Vue 构建产物。
# 尚未构建前保留原静态页作为回退，避免后端无法启动。
WEB_DIR = VUE_DIST_DIR if VUE_DIST_DIR.is_dir() else LEGACY_WEB_DIR


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """
    在 FastAPI 生命周期中初始化并清理 Agent 加载器。
    """
    # 持久化连接属于应用级资源，不能在每个请求中重复创建。
    await agent_loader.initialize()
    cleanup_stop_event = asyncio.Event()
    cleanup_task = asyncio.create_task(run_visualization_cleanup(cleanup_stop_event))
    try:
        yield
    finally:
        cleanup_stop_event.set()
        cleanup_task.cancel()
        try:
            with suppress(asyncio.CancelledError):
                await cleanup_task
        finally:
            await agent_loader.shutdown()


app = FastAPI(title="ERP 采购智能助手", lifespan=lifespan)

def _mount_web_assets(application: FastAPI, web_dir: Path) -> None:
    """
    挂载前端资源目录，兼容 Vite 默认的 /assets 和已有 /static 路径。
    """
    application.mount("/static", StaticFiles(directory=web_dir), name="static")
    assets_dir = web_dir / "assets"
    if assets_dir.is_dir():
        application.mount("/assets", StaticFiles(directory=assets_dir), name="assets")


# 只公开选定的前端目录，不将项目根目录作为静态资源入口。
_mount_web_assets(app, WEB_DIR)


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    """
    返回当前可用的聊天首页文件。
    """
    return FileResponse(WEB_DIR / "index.html")


@app.get("/visualizations/{artifact_id}", include_in_schema=False, response_model=None)
async def visualization(artifact_id: str, download: bool = False) -> FileResponse | Response:
    """
    返回图表资源，或在 ``download`` 时将 HTML 图表作为附件下载。

    资源过期或被清理后始终返回占位图，避免下载端点泄露已删除文件的路径信息。
    """
    path = get_visualization_path(artifact_id)
    if path is None:
        return Response(
            content=EXPIRED_VISUALIZATION_SVG,
            media_type="image/svg+xml",
            headers={"Cache-Control": "no-store"},
        )
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    headers = {"X-Content-Type-Options": "nosniff"}
    if media_type == "text/html":
        # 图表 HTML 来自外部 MCP；新窗口仍需运行图表脚本，但不得访问主应用上下文。
        headers["Content-Security-Policy"] = "sandbox allow-scripts"
        if download:
            # 仅 HTML 资源提供下载，避免历史 PNG 记录被误认为当前交互式图表。
            headers["Content-Disposition"] = f'attachment; filename="chart-{artifact_id}.html"'
    return FileResponse(path, media_type=media_type, headers=headers)


@app.get("/analysis/reports/{report_id}", include_in_schema=False, response_model=None)
async def download_analysis_report(
    report_id: str,
    user_id: str = Query(..., min_length=1),
) -> Response:
    """在用户下载时按归属从沙箱读取 Markdown，不在项目目录保留副本。"""
    downloaded = await agent_loader.download_sandbox_report(user_id, report_id)
    if downloaded is None:
        raise HTTPException(status_code=404, detail="报告不存在、已过期或无权访问")
    filename, content = downloaded
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
        },
    )


def _extract_answer(result: Any) -> str:
    """
    从 Agent 返回结果中提取最后一条助手消息的文本。
    """
    # DeepAgents 版本和调用方式可能返回字符串、状态字典或消息对象。
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        messages = result.get("messages")
        if messages:
            last_message = messages[-1]
            content = getattr(last_message, "content", None)
            if content is None and isinstance(last_message, dict):
                content = last_message.get("content")
            return content_to_text(content)
        return content_to_text(result.get("answer", result.get("output", "")))
    return content_to_text(getattr(result, "content", result))


async def _bind_async_tasks_from_result(
    result: Any,
    *,
    user_id: str,
    username: str,
    thread_id: str,
) -> None:
    """为非流式 Agent 结果登记异步任务归属。

    流式响应会在工具消息到达时绑定任务；``ainvoke`` 会一次性返回相同的最终消息列表，
    因此必须在客户端开始轮询任务状态前完成同样的登记。
    """
    messages = result.get("messages", []) if isinstance(result, dict) else []
    for message in messages:
        tool_name = getattr(message, "name", None)
        content = getattr(message, "content", None)
        status = getattr(message, "status", None)
        if isinstance(message, dict):
            tool_name = message.get("name", tool_name)
            content = message.get("content", content)
            status = message.get("status", status)
        if tool_name != "start_async_task" or status == "error":
            continue
        task_id = extract_async_task_id(content)
        if task_id:
            await agent_loader.bind_async_task(
                task_id,
                user_id=user_id,
                username=username,
                thread_id=thread_id,
            )


def _create_sse_message(data: dict[str, Any]) -> str:
    """
    将事件数据编码为浏览器可解析的 SSE 消息。
    """
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _get_stream_message(chunk: Any) -> tuple[Any, dict[str, Any]] | None:
    """
    从 LangGraph 消息流事件中提取 token 和元数据。
    """
    if isinstance(chunk, dict):
        if chunk.get("type") != "messages":
            return None
        data = chunk.get("data")
    else:
        data = chunk

    if not isinstance(data, (list, tuple)) or len(data) != 2:
        return None
    token, metadata = data
    return token, metadata if isinstance(metadata, dict) else {}


def _get_tool_chunks(token: Any) -> list[dict[str, Any]]:
    """
    读取模型增量消息中的工具调用分片。
    """
    tool_call_chunks = getattr(token, "tool_call_chunks", None) or []
    return [chunk for chunk in tool_call_chunks if isinstance(chunk, dict)]


def _is_tool_result(token: Any) -> bool:
    """
    判断当前流式 token 是否为工具返回结果。
    """
    return getattr(token, "type", None) == "tool"


def _get_interrupt_values(chunk: Any) -> list[Any]:
    """
    从 LangGraph values 流事件中读取待处理的中断值。

    LangGraph 版本会将 interrupts 放在事件顶层或 data 内；
    两种结构均需兼容，避免升级后前端无法恢复暂停的会话。
    """
    return [getattr(item, "value", item) for item in _get_stream_interrupts(chunk)]


def _get_stream_interrupts(chunk: Any) -> list[Any]:
    """
    保留流式中断对象及其 ID，使 SSE 和历史使用同一恢复协议。
    """
    if not isinstance(chunk, dict) or chunk.get("type") != "values":
        return []
    interrupts = chunk.get("interrupts")
    if interrupts is None and isinstance(chunk.get("data"), dict):
        interrupts = chunk["data"].get("interrupts")
    return list(interrupts or [])


def _get_stream_source(chunk: Any, metadata: dict[str, Any] | None = None) -> str:
    """
    返回主 Agent 或子 Agent 的稳定原名。

    DeepAgents 为声明式子 Agent 注入 ``lc_agent_name`` 元数据；
    namespace 只作为旧版本或异常事件的来源兜底，不能用于猜测具体子 Agent 名称。
    """
    for key in ("lc_agent_name", "subagent_name", "agent_name"):
        value = (metadata or {}).get(key)
        if value:
            return str(value)
    namespace = chunk.get("ns", ()) if isinstance(chunk, dict) else ()
    return "subagent" if namespace else "main"


def _is_subagent_stream(source: str) -> bool:
    """判断消息流是否来自不应直接展示的子 Agent 内部执行。"""
    return source != "main"


def _is_internal_middleware_stream(metadata: dict[str, Any]) -> bool:
    """判断消息是否来自不应向用户展示的内部记忆更新模型调用。"""
    return metadata.get("langgraph_node") == "MemoryUpdateMiddleware.after_agent"


def _get_subagent_name(value: Any) -> str | None:
    """从 task 工具参数中读取声明式子 Agent 原名。"""
    if isinstance(value, dict):
        name = value.get("subagent_type")
        return str(name) if name else None
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return _get_subagent_name(parsed)
    match = re.search(r"['\"]subagent_type['\"]\s*:\s*['\"]([^'\"\\]+)", value)
    return match.group(1) if match else None


def _serialize_tool_args(args: Any) -> str:
    """将工具参数编码为前端可稳定解析的文本。"""
    if isinstance(args, (dict, list, tuple)):
        return json.dumps(args, ensure_ascii=False)
    return str(args)


async def _run_chat(request: ChatRequest) -> ChatResponse:
    """
    在会话 guard 中校验归属并执行非流式对话。
    """
    thread_id = request.thread_id or str(uuid.uuid4())
    async with agent_loader.thread_operation(thread_id):
        if request.thread_id:
            await agent_loader.require_session(request.user_id, thread_id)
        await agent_loader.save_session(request.user_id, thread_id, make_session_title(request.message))
        return await _run_chat_unlocked(request, thread_id)


async def _run_chat_unlocked(request: ChatRequest, thread_id: str) -> ChatResponse:
    """
    执行一轮非流式对话，并返回标准化响应。
    """
    username = request.username or request.user_id
    agent = await agent_loader.get_agent_for_user(
        user_id=request.user_id,
        username=username,
        thread_id=thread_id,
    )
    # thread_id 用于 checkpoint 恢复会话，user_id 和 username 用于 Agent 身份隔离。
    config = agent_loader.create_config(
        thread_id=thread_id,
        user_id=request.user_id,
        username=username,
    )
    context = ProcurementContext(
        user_id=request.user_id,
        username=username,
    )

    try:
        agent_input = {"messages": [{"role": "user", "content": request.message}]}
        result = await agent.ainvoke(
            agent_input,
            config=config,
            context=context,
        )
    except Exception as exc:
        # 记录异常类型和消息，便于区分模型、数据库或配置问题；
        logger.exception("Agent 调用异常: %s", type(exc).__name__)
        if type(exc).__name__ in {
            "OpenAIConnectionError",
            "APIConnectionError",
            "ConnectError",
        }:
            raise HTTPException(
                status_code=503,
                detail="模型服务暂时不可用，请检查网络和 DEEPSEEK_BASE_URL 配置",
            ) from exc
        raise HTTPException(status_code=500, detail="Agent 调用失败") from exc

    answer = _extract_answer(result).strip()
    interrupts = result.get("__interrupt__", []) if isinstance(result, dict) else []
    if not answer and not interrupts:
        raise HTTPException(status_code=502, detail="Agent 未返回有效回答")
    await _bind_async_tasks_from_result(
        result,
        user_id=request.user_id,
        username=username,
        thread_id=thread_id,
    )
    await agent_loader.save_session(
        request.user_id,
        thread_id,
        make_session_title(request.message),
    )
    return ChatResponse(
        thread_id=thread_id,
        user_id=request.user_id,
        username=username,
        answer=answer,
        interrupt=_serialize_interrupt(interrupts[0], thread_id) if interrupts else None,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    接收一条消息并返回完整的 Agent 回答。
    """
    return await _run_chat(request)


async def _stream_response(
    request: ChatRequest | ResumeChatRequest,
    *,
    thread_id: str,
    agent_input: dict[str, Any] | Command,
    is_resume: bool,
) -> AsyncIterator[str]:
    """
    在整个 SSE 生命周期持有会话 guard，取消和异常时也释放。
    """
    try:
        async with agent_loader.thread_operation(thread_id):
            if is_resume or getattr(request, "thread_id", None):
                await agent_loader.require_session(request.user_id, thread_id)
            async with aclosing(_stream_response_unlocked(
                request, thread_id=thread_id, agent_input=agent_input, is_resume=is_resume,
            )) as response:
                async for event in response:
                    yield event
    except HTTPException as exc:
        yield _create_sse_message({"type": "error", "message": exc.detail, "status_code": exc.status_code})


async def _stream_response_unlocked(
    request: ChatRequest | ResumeChatRequest,
    *,
    thread_id: str,
    agent_input: dict[str, Any] | Command,
    is_resume: bool,
) -> AsyncIterator[str]:
    """
    流式发送 Agent 文本、工具和中断事件。

    初始调用与 Command 恢复共享同一条流式处理链，
    确保恢复后仍能再次触发缺字段或审批中断，并沿用原始 checkpoint。
    """
    username = request.username or request.user_id

    # 原始工具 ID 跨请求和 checkpoint 稳定，不能改成请求内随机展示 ID。
    # 仅用消息与分片索引关联后续不再携带 ID 的参数增量。
    tool_call_ids: dict[str, str] = {}
    tool_subagent_names: dict[str, str] = {}
    pending_tool_ids: set[str] = set()
    pending_interrupts: dict[str, dict[str, Any]] = {}
    answer_parts: list[str] = []
    assistant_message_id: str | None = None

    def _tool_event_id(tool_chunk: dict[str, Any], message_id: str) -> str:
        """
        为同一工具调用的多个分片分配稳定的前端展示 ID。
        """
        chunk_index = tool_chunk.get("index", 0)
        chunk_key = f"{message_id}:{chunk_index}"
        source_id = tool_chunk.get("id")
        if source_id:
            tool_call_ids[chunk_key] = str(source_id)
        return tool_call_ids.setdefault(chunk_key, chunk_key)

    stream = None
    try:
        if not is_resume:
            assert isinstance(request, ChatRequest)
            # 中断发生前也必须建立会话索引，否则前端无法用 thread_id 恢复它。
            await agent_loader.save_session(
                request.user_id,
                thread_id,
                make_session_title(request.message),
            )
        agent = await agent_loader.get_agent_for_user(
            user_id=request.user_id,
            username=username,
            thread_id=thread_id,
        )
        config = agent_loader.create_config(
            thread_id=thread_id,
            user_id=request.user_id,
            username=username,
        )
        context = ProcurementContext(user_id=request.user_id, username=username)
        # 必须使用异步流式调用：MCP StructuredTool 不支持同步 invoke/stream。
        # values 流用于捕获 interrupt。仍订阅子图以保证审批和补充信息能冒泡，
        # 但普通子 Agent 事件仅是内部执行细节，不发送给用户界面。
        stream = agent.astream(
            agent_input,
            config=config,
            context=context,
            stream_mode=["messages", "values"],
            subgraphs=True,
            version="v2",
        )
        async for chunk in stream:
            interrupt_values = _get_stream_interrupts(chunk)
            if interrupt_values:
                for interrupt_value in interrupt_values:
                    event = _serialize_interrupt(interrupt_value, thread_id)
                    key = event.get("interrupt_id") or json.dumps(event, sort_keys=True)
                    pending_interrupts[key] = event
                # 子图先发出中断，父图随后才保存可恢复状态。必须耗尽流，让中断
                # 冒泡并完成 checkpoint；此处关闭流会导致刷新后丢失审批表单。
                continue

            stream_message = _get_stream_message(chunk)
            if stream_message is None:
                continue
            token, metadata = stream_message
            if _is_internal_middleware_stream(metadata):
                continue
            source = _get_stream_source(chunk, metadata)
            if _is_subagent_stream(source):
                continue
            message_id = str(getattr(token, "id", None) or uuid.uuid4())
            tool_chunks = _get_tool_chunks(token)

            for tool_chunk in tool_chunks:
                assistant_message_id = None
                # 工具参数可能跨多个 chunk 返回。首次收到工具名称时发送开始事件，
                # 之后仅增量发送参数，避免前端重复创建工具消息。
                tool_call_id = _tool_event_id(tool_chunk, message_id)
                tool_name = tool_chunk.get("name")
                args = tool_chunk.get("args")
                if tool_name and tool_call_id not in pending_tool_ids:
                    pending_tool_ids.add(tool_call_id)
                    start_event = {
                        "type": "tool_start",
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "source": source,
                    }
                    subagent_name = _get_subagent_name(args)
                    if subagent_name:
                        tool_subagent_names[tool_call_id] = subagent_name
                        start_event["subagent_name"] = subagent_name
                    yield _create_sse_message(start_event)

                if args:
                    args_text = _serialize_tool_args(args)
                    args_event = {
                        "type": "tool_args",
                        "tool_call_id": tool_call_id,
                        "args": args_text,
                        "source": source,
                    }
                    subagent_name = _get_subagent_name(args)
                    if subagent_name:
                        tool_subagent_names[tool_call_id] = subagent_name
                        args_event["subagent_name"] = subagent_name
                    yield _create_sse_message(args_event)

            if _is_tool_result(token):
                assistant_message_id = None
                # 工具结果到达后更新对应占位消息，并按固定顺序发送 result/end，
                # 让前端能够结束加载状态并展示完整结果。
                source_id = str(getattr(token, "tool_call_id", ""))
                tool_call_id = source_id
                tool_name = str(getattr(token, "name", "MCP 工具"))
                tool_status = "error" if getattr(token, "status", None) == "error" else "done"
                result_text = content_to_text(getattr(token, "content", ""))
                visualization = extract_visualization(getattr(token, "content", ""))
                pending_tool_ids.discard(tool_call_id)
                if tool_name == "start_async_task" and tool_status != "error":
                    task_id = extract_async_task_id(getattr(token, "content", ""))
                    if task_id:
                        await agent_loader.bind_async_task(
                            task_id,
                            user_id=request.user_id,
                            username=username,
                            thread_id=thread_id,
                        )
                result_event = {
                    "type": "tool_result",
                    "tool_call_id": tool_call_id,
                    "tool_name": tool_name,
                    "text": result_text,
                    "source": source,
                    "status": tool_status,
                    "tool_status": tool_status,
                }
                if visualization:
                    result_event["visualization"] = visualization
                subagent_name = tool_subagent_names.get(tool_call_id)
                if subagent_name:
                    result_event["subagent_name"] = subagent_name
                yield _create_sse_message(result_event)
                yield _create_sse_message(
                    {
                        "type": "tool_end",
                        "status": tool_status,
                        "tool_status": tool_status,
                        "tool_call_id": tool_call_id,
                        "tool_name": tool_name,
                        "source": source,
                    }
                )
                continue

            content = content_to_text(getattr(token, "content", ""))
            if not content or tool_chunks:
                continue
            if assistant_message_id is None:
                assistant_message_id = f"assistant-{uuid.uuid4()}"
            answer_parts.append(content)
            yield _create_sse_message(
                {
                    "type": "token",
                    "message_id": assistant_message_id,
                    "content": content,
                    "source": source,
                }
            )

        # 只有图已结束并完成持久化后才开放人工恢复；同一中断会跨图冒泡，按 ID 去重。
        # 子图事件可能携带中间层 ID；恢复必须使用根图 checkpoint 中的最终 ID，
        # 否则 Command 会重放子图并再次产生同一审批，而不会执行已批准的工具。
        get_state = getattr(agent, "aget_state", None)
        if pending_interrupts and callable(get_state):
            state = await get_state(config)
            checkpoint_interrupts = getattr(state, "interrupts", ()) or ()
            canonical_interrupts = [
                _serialize_interrupt(interrupt, thread_id)
                for interrupt in checkpoint_interrupts
            ]
            if canonical_interrupts:
                pending_interrupts = {
                    event.get("interrupt_id") or json.dumps(event, sort_keys=True): event
                    for event in canonical_interrupts
                }
        for event in pending_interrupts.values():
            yield _create_sse_message(event)
        for tool_call_id in pending_tool_ids:
            yield _create_sse_message({"type": "tool_end", "tool_call_id": tool_call_id})
        yield _create_sse_message(
            {
                "type": "done",
                "thread_id": thread_id,
                "user_id": request.user_id,
                "username": username,
                "content": "".join(answer_parts),
                "interrupted": bool(pending_interrupts),
            }
        )
    except Exception as exc:
        logger.exception("Agent 流式调用异常: %s", type(exc).__name__)
        for tool_call_id in pending_tool_ids:
            yield _create_sse_message({"type": "tool_end", "tool_call_id": tool_call_id})
        yield _create_sse_message({"type": "error", "message": "Agent 调用失败"})
    finally:
        if stream is not None:
            await stream.aclose()


@router.post("/chat/stream")
async def chat_stream(request: ChatRequest) -> StreamingResponse:
    """
    以 SSE 格式发送一条消息的流式回答和完成事件。
    """
    # 禁用代理缓冲，确保 token 和工具状态在生成时立即到达浏览器。
    thread_id = request.thread_id or str(uuid.uuid4())
    if request.thread_id:
        await agent_loader.require_session(request.user_id, thread_id)
    agent_input = {"messages": [{"role": "user", "content": request.message}]}
    return StreamingResponse(
        _stream_response(
            request,
            thread_id=thread_id,
            agent_input=agent_input,
            is_resume=False,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat/{thread_id}/resume")
async def resume_chat(thread_id: str, request: ResumeChatRequest) -> StreamingResponse:
    """
    向同一会话的暂停图提交补充信息或审批决策，并恢复流式执行。
    """
    if await agent_loader.get_session(request.user_id, thread_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在或无权恢复")
    return StreamingResponse(
        _stream_response(
            request,
            thread_id=thread_id,
            agent_input=Command(resume=request.resume),
            is_resume=True,
        ),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.include_router(router)
app.include_router(history_router)
app.include_router(async_tasks_router)
app.include_router(auth_router)
