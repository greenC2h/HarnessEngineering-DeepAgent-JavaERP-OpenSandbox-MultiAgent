"""API 归属、会话互斥和异步投递的行为回归测试。"""

from __future__ import annotations

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.types import Command, interrupt

from agent.schema import AsyncTaskBinding, ChatRequest, ResumeChatRequest
from api.agent_loader import AgentLoader
from api.async_tasks import get_async_task_status, router as async_tasks_router
from api.chat import _run_chat, _stream_response, chat_stream, resume_chat
from api.history import serialize_messages


class ThreadCoordinationTests(unittest.IsolatedAsyncioTestCase):
    """所有会话写入使用同一个 guard，检查与写入之间不允许删除穿插。"""

    def setUp(self) -> None:
        self.loader = AgentLoader()
        self.loader._initialized = True
        self.loader._store = SimpleNamespace(adelete=AsyncMock())
        self.loader._checkpointer = SimpleNamespace(adelete_thread=AsyncMock())
        self.loader.get_session = AsyncMock(return_value={"thread_id": "thread"})
        self.loader.get_async_task_binding = AsyncMock(
            return_value=AsyncTaskBinding("task", "u1", "user", "thread")
        )
        self.loader.get_thread_state = AsyncMock(
            return_value=SimpleNamespace(values={"messages": []}, next=(), interrupts=())
        )
        self.agent = SimpleNamespace(aupdate_state=AsyncMock())
        self.loader.get_agent_for_user = AsyncMock(return_value=self.agent)
        self.loader.save_session = AsyncMock()

    async def test_busy_thread_defers_publish_and_rejects_delete(self) -> None:
        async with self.loader.thread_operation("thread"):
            self.assertFalse(await self.loader.publish_async_task_result("task", content="report", artifact=None))
            with self.assertRaises(HTTPException) as raised:
                await self.loader.delete_session("u1", "thread")
            self.assertEqual(raised.exception.status_code, 409)
        self.agent.aupdate_state.assert_not_awaited()
        self.loader._checkpointer.adelete_thread.assert_not_awaited()
        self.assertTrue(await self.loader.publish_async_task_result("task", content="report", artifact=None))

    async def test_deleted_parent_is_not_recreated_by_delayed_result(self) -> None:
        await self.loader.delete_session("u1", "thread")
        self.loader.get_session.return_value = None
        self.assertFalse(await self.loader.publish_async_task_result("task", content="report", artifact=None))
        self.agent.aupdate_state.assert_not_awaited()
        self.loader.save_session.assert_not_awaited()

    async def test_paused_parent_defers_publish(self) -> None:
        for next_nodes, interrupts in [(('tools',), ()), ((), (SimpleNamespace(value={}),))]:
            self.loader.get_thread_state.return_value = SimpleNamespace(
                values={"messages": []}, next=next_nodes, interrupts=interrupts,
            )
            self.assertFalse(await self.loader.publish_async_task_result("task", content="report", artifact=None))
        self.agent.aupdate_state.assert_not_awaited()

    async def test_concurrent_publish_is_deferred_then_idempotent(self) -> None:
        entered, release = asyncio.Event(), asyncio.Event()

        async def update(*args, **kwargs):
            entered.set()
            await release.wait()
            self.loader.get_thread_state.return_value.values["messages"] = args[1]["messages"]

        self.agent.aupdate_state.side_effect = update
        first = asyncio.create_task(self.loader.publish_async_task_result("task", content="report", artifact=None))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            self.assertFalse(await self.loader.publish_async_task_result("task", content="report", artifact=None))
        finally:
            release.set()
            await first
        self.assertTrue(await self.loader.publish_async_task_result("task", content="report", artifact=None))
        self.agent.aupdate_state.assert_awaited_once()

    async def test_cancelled_operation_releases_guard(self) -> None:
        entered = asyncio.Event()

        async def run():
            async with self.loader.thread_operation("thread"):
                entered.set()
                await asyncio.Event().wait()

        task = asyncio.create_task(run())
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        async with self.loader.thread_operation("thread") as acquired:
            self.assertTrue(acquired)

class ChatOwnershipTests(unittest.IsolatedAsyncioTestCase):
    """已有 thread 必须属于用户，未指定 thread 的新对话仍可创建。"""

    async def test_nested_interrupt_is_durable_before_sse_finishes(self) -> None:
        """
        子图中断必须冒泡并完成父图 checkpoint，刷新与恢复才能找到同一中断。
        """
        saver = InMemorySaver()

        def ask_for_details(state):
            answer = interrupt({"type": "information_request", "information_needed": "编号"})
            return {"messages": [AIMessage(content=answer["information"])]}

        child = StateGraph(MessagesState)
        child.add_node("ask", ask_for_details)
        child.add_edge(START, "ask")
        child.add_edge("ask", END)
        parent = StateGraph(MessagesState)
        parent.add_node("tools", child.compile())
        parent.add_edge(START, "tools")
        parent.add_edge("tools", END)
        agent = parent.compile(checkpointer=saver)
        loader = AgentLoader()
        loader.get_session = AsyncMock(return_value={})
        loader.save_session = AsyncMock()
        loader.get_agent_for_user = AsyncMock(return_value=agent)
        config = loader.create_config(thread_id="nested", user_id="u1", username="user")
        with patch("api.chat.agent_loader", loader):
            events = [json.loads(item.removeprefix("data: ")) async for item in _stream_response(
                ChatRequest(message="test", user_id="u1", thread_id="nested"),
                thread_id="nested", agent_input={"messages": [("user", "test")]}, is_resume=False,
            )]
            paused = await agent.aget_state(config)
            self.assertEqual(len(paused.interrupts), 1)
            interrupt_events = [event for event in events if event["type"] == "interrupt"]
            self.assertEqual(len(interrupt_events), 1)
            self.assertEqual(interrupt_events[0]["interrupt_id"], paused.interrupts[0].id)
            self.assertTrue(events[-1]["interrupted"])
            resumed = [json.loads(item.removeprefix("data: ")) async for item in _stream_response(
                ResumeChatRequest(resume={"information": "NESTED-42"}, user_id="u1"),
                thread_id="nested", agent_input=Command(resume={"information": "NESTED-42"}), is_resume=True,
            )]
        self.assertEqual(resumed[-1]["type"], "done")
        self.assertFalse(resumed[-1]["interrupted"])
        final = await agent.aget_state(config)
        self.assertFalse(final.interrupts)
        self.assertFalse(final.next)
        self.assertEqual(final.values["messages"][-1].content, "NESTED-42")

    async def test_parallel_interrupts_resume_one_id_at_a_time(self) -> None:
        """
        两个子图同时暂停时，响应当前表单不能错误回答另一个子图。
        """
        saver = InMemorySaver()
        parent = StateGraph(MessagesState)
        for name in ("first", "second"):
            def ask(state, label=name):
                answer = interrupt({"type": "information_request", "information_needed": label})
                return {"messages": [AIMessage(content=f"{label}:{answer['information']}")]}

            child = StateGraph(MessagesState)
            child.add_node("ask", ask)
            child.add_edge(START, "ask")
            child.add_edge("ask", END)
            parent.add_node(name, child.compile())
            parent.add_edge(START, name)
            parent.add_edge(name, END)
        agent = parent.compile(checkpointer=saver)
        loader = AgentLoader()
        loader.get_session = AsyncMock(return_value={})
        loader.save_session = AsyncMock()
        loader.get_agent_for_user = AsyncMock(return_value=agent)
        config = loader.create_config(thread_id="parallel", user_id="u1", username="user")
        with patch("api.chat.agent_loader", loader):
            initial = [json.loads(item.removeprefix("data: ")) async for item in _stream_response(
                ChatRequest(message="test", user_id="u1", thread_id="parallel"),
                thread_id="parallel", agent_input={"messages": [("user", "test")]}, is_resume=False,
            )]
            self.assertEqual(sum(item["type"] == "interrupt" for item in initial), 2)
            paused = await agent.aget_state(config)
            by_name = {item.value["information_needed"]: item.id for item in paused.interrupts}
            for label in ("second", "first"):
                response = {by_name[label]: {"information": f"answer-{label}"}}
                events = [json.loads(item.removeprefix("data: ")) async for item in _stream_response(
                    ResumeChatRequest(resume=response, user_id="u1"),
                    thread_id="parallel", agent_input=Command(resume=response), is_resume=True,
                )]
                self.assertFalse(any(item["type"] == "error" for item in events))
                self.assertEqual(events[-1]["interrupted"], label == "second")
        final = await agent.aget_state(config)
        self.assertFalse(final.interrupts)
        self.assertEqual(
            {message.content for message in final.values["messages"] if isinstance(message, AIMessage)},
            {"first:answer-first", "second:answer-second"},
        )

    async def test_tool_error_is_preserved_in_result_and_end_events(self) -> None:
        async def stream(*args, **kwargs):
            yield {"type": "messages", "data": (
                ToolMessage(content="ERP unavailable", tool_call_id="call", name="request_erp", status="error"), {},
            )}

        loader = AgentLoader()
        loader.get_session = AsyncMock(return_value={})
        loader.save_session = AsyncMock()
        loader.get_agent_for_user = AsyncMock(return_value=SimpleNamespace(astream=stream))
        with patch("api.chat.agent_loader", loader):
            output = [json.loads(item.removeprefix("data: ")) async for item in _stream_response(
                ChatRequest(message="hi", user_id="u1", thread_id="thread"),
                thread_id="thread", agent_input={}, is_resume=False,
            )]
        for event in output:
            if event["type"] in {"tool_result", "tool_end"}:
                self.assertEqual(event["status"], "error")
                self.assertEqual(event["tool_status"], "error")

    async def test_closing_sse_closes_agent_stream_before_releasing_guard(self) -> None:
        closed = asyncio.Event()

        async def stream(*args, **kwargs):
            try:
                yield {"type": "messages", "data": (AIMessageChunk(content="hello", id="m1"), {})}
            finally:
                self.assertIn("thread", loader._active_threads)
                closed.set()

        loader = AgentLoader()
        loader.get_session = AsyncMock(return_value={})
        loader.save_session = AsyncMock()
        loader.get_agent_for_user = AsyncMock(return_value=SimpleNamespace(astream=stream))
        with patch("api.chat.agent_loader", loader):
            response = _stream_response(
                ChatRequest(message="hi", user_id="u1", thread_id="thread"),
                thread_id="thread", agent_input={}, is_resume=False,
            )
            await anext(response)
            await response.aclose()
        self.assertTrue(closed.is_set())
        self.assertNotIn("thread", loader._active_threads)

    async def test_unknown_thread_rejected_by_all_chat_entries(self) -> None:
        loader = AgentLoader()
        loader.get_session = AsyncMock(return_value=None)
        loader.save_session = AsyncMock()
        loader.get_agent_for_user = AsyncMock()
        with patch("api.chat.agent_loader", loader):
            for call in (
                lambda: _run_chat(ChatRequest(message="hello", user_id="u2", thread_id="other")),
                lambda: chat_stream(ChatRequest(message="hello", user_id="u2", thread_id="other")),
                lambda: resume_chat("other", ResumeChatRequest(resume={}, user_id="u2")),
            ):
                with self.assertRaises(HTTPException) as raised:
                    await call()
                self.assertEqual(raised.exception.status_code, 404)
        loader.save_session.assert_not_awaited()
        loader.get_agent_for_user.assert_not_awaited()

    async def test_new_chat_without_thread_is_created(self) -> None:
        loader = AgentLoader()
        loader.save_session = AsyncMock()
        loader.get_session = AsyncMock()
        loader.get_agent_for_user = AsyncMock(return_value=SimpleNamespace(
            ainvoke=AsyncMock(return_value={"messages": [{"content": "hello"}]})
        ))
        with patch("api.chat.agent_loader", loader):
            response = await _run_chat(ChatRequest(message="hi", user_id="u1"))
        self.assertTrue(response.thread_id)
        self.assertEqual(response.answer, "hello")
        loader.get_session.assert_not_awaited()

    async def test_stream_checks_ownership_again_after_response_creation(self) -> None:
        loader = AgentLoader()
        loader.get_session = AsyncMock(side_effect=[{}, None])
        loader.get_agent_for_user = AsyncMock()
        with patch("api.chat.agent_loader", loader):
            response = await chat_stream(ChatRequest(message="hi", user_id="u1", thread_id="thread"))
            events = [json.loads(item.removeprefix("data: ")) async for item in response.body_iterator]
        self.assertEqual(events[0]["status_code"], 404)
        loader.get_agent_for_user.assert_not_awaited()

    async def test_stream_chunks_keep_ids_for_parallel_tools_and_later_model_calls(self) -> None:
        events = []
        for message_id, call_id in [("m1", "c1"), ("m2", "c3")]:
            events.append(AIMessageChunk(id=message_id, content="", tool_call_chunks=[
                {"name": "query", "id": call_id, "index": 0, "args": '{"q":'},
            ]))
            if message_id == "m1":
                events.append(AIMessageChunk(id=message_id, content="", tool_call_chunks=[
                    {"name": "other", "id": "c2", "index": 1, "args": "{}"},
                ]))
            events.append(AIMessageChunk(id=message_id, content="", tool_call_chunks=[
                {"name": None, "id": None, "index": 0, "args": '"value"}'},
            ]))
            events.append(ToolMessage(content="ok", name="query", tool_call_id=call_id))
        events.append(ToolMessage(content="ok", name="other", tool_call_id="c2"))

        async def stream(*args, **kwargs):
            for event in events:
                yield {"type": "messages", "data": (event, {}), "ns": ()}

        loader = AgentLoader()
        loader.get_session = AsyncMock(return_value={})
        loader.save_session = AsyncMock()
        loader.get_agent_for_user = AsyncMock(return_value=SimpleNamespace(astream=stream))
        with patch("api.chat.agent_loader", loader):
            output = [json.loads(item.removeprefix("data: ")) async for item in _stream_response(
                ChatRequest(message="hi", user_id="u1", thread_id="thread"),
                thread_id="thread", agent_input={}, is_resume=False,
            )]
        starts = [item for item in output if item["type"] == "tool_start"]
        self.assertEqual({item["tool_call_id"] for item in starts}, {"c1", "c2", "c3"})
        for item in starts:
            related = [entry for entry in output if entry.get("tool_call_id") == item["tool_call_id"]]
            self.assertEqual(sum(entry["type"] == "tool_result" for entry in related), 1)
            self.assertEqual(sum(entry["type"] == "tool_end" for entry in related), 1)
            if item["tool_name"] == "query":
                self.assertEqual(''.join(entry["args"] for entry in related if entry["type"] == "tool_args"), '{"q":"value"}')

    async def test_initial_resume_and_history_share_canonical_tool_id(self) -> None:
        """恢复请求没有上一请求的映射，结果仍应匹配初始或历史恢复的工具卡片。"""
        call_id = "call_order_approval"
        calls = []

        async def stream(agent_input, **kwargs):
            calls.append(agent_input)
            if isinstance(agent_input, Command):
                yield {"type": "messages", "data": (
                    ToolMessage(content="Order created", tool_call_id=call_id, name="create_order"), {},
                )}
            else:
                yield {"type": "messages", "data": (
                    AIMessageChunk(id="m1", content="", tool_call_chunks=[{
                        "name": "create_order", "id": call_id, "index": 0, "args": '{"quantity":',
                    }]), {},
                )}
                yield {"type": "messages", "data": (
                    AIMessageChunk(id="m1", content="", tool_call_chunks=[{
                        "name": None, "id": None, "index": 0, "args": '1}',
                    }]), {},
                )}
                yield {"type": "values", "interrupts": [SimpleNamespace(
                    id="approval", value={"action_requests": [{"name": "create_order", "args": {"quantity": 1}}]},
                )]}

        loader = AgentLoader()
        loader.get_session = AsyncMock(return_value={})
        loader.save_session = AsyncMock()
        loader.get_agent_for_user = AsyncMock(return_value=SimpleNamespace(astream=stream))
        with patch("api.chat.agent_loader", loader):
            initial = await chat_stream(ChatRequest(message="create", user_id="u1", thread_id="thread"))
            initial_events = [json.loads(item.removeprefix("data: ")) async for item in initial.body_iterator]
            resumed = await resume_chat("thread", ResumeChatRequest(user_id="u1", resume={"decisions": [{"type": "approve"}]}))
            resumed_events = [json.loads(item.removeprefix("data: ")) async for item in resumed.body_iterator]

        card_id = next(event["tool_call_id"] for event in initial_events if event["type"] == "tool_start")
        self.assertEqual(card_id, call_id)
        self.assertTrue(initial_events[-1]["interrupted"])
        self.assertEqual(len(calls), 2)
        self.assertIsInstance(calls[1], Command)
        for event in initial_events + resumed_events:
            if "tool_call_id" in event:
                self.assertEqual(event["tool_call_id"], card_id)
        result = next(event for event in resumed_events if event["type"] == "tool_result")
        self.assertEqual(result["text"], "Order created")
        history_card = serialize_messages([AIMessage(content="", tool_calls=[{
            "id": call_id, "name": "create_order", "args": {"quantity": 1},
        }])])[0]
        self.assertEqual(history_card.id, result["tool_call_id"])


class AsyncStatusBoundaryTests(unittest.IsolatedAsyncioTestCase):
    """远程状态读取必须晚于归属校验，读取失败不得投递。"""

    async def asyncSetUp(self) -> None:
        self.loader = AgentLoader()
        self.loader.get_async_task_binding = AsyncMock(return_value=AsyncTaskBinding("task", "u1", "user", "thread"))
        self.loader.require_session = AsyncMock()
        self.loader.publish_async_task_result = AsyncMock(return_value=True)
        self.client = SimpleNamespace(
            runs=SimpleNamespace(list=AsyncMock(return_value=[{"status": "success"}])),
            threads=SimpleNamespace(get_state=AsyncMock(return_value={"values": {"messages": []}})),
        )
        self.enterContext(patch("api.async_tasks.agent_loader", self.loader))
        self.get_client = self.enterContext(patch("api.async_tasks.get_client", return_value=self.client))

    async def test_wrong_owner_is_rejected_before_remote_io(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            await get_async_task_status("task", user_id="u2")
        self.assertEqual(raised.exception.status_code, 404)
        self.get_client.assert_not_called()

    async def test_status_http_route_requires_user_id(self) -> None:
        application = FastAPI()
        application.include_router(async_tasks_router)
        with TestClient(application) as client:
            self.assertEqual(client.get("/async-tasks/task").status_code, 422)
            self.assertEqual(client.get("/async-tasks/task?user_id=").status_code, 422)
        self.get_client.assert_not_called()

    async def test_state_failure_is_retryable_without_false_delivery(self) -> None:
        self.client.threads.get_state.side_effect = OSError("secret upstream error")
        with self.assertRaises(HTTPException) as raised:
            await get_async_task_status("task", user_id="u1")
        self.assertEqual(raised.exception.status_code, 502)
        self.assertNotIn("secret", raised.exception.detail)
        self.loader.publish_async_task_result.assert_not_awaited()
        self.client.threads.get_state.side_effect = None
        self.client.threads.get_state.return_value = {"values": {"messages": [{"type": "ai", "content": "actual report"}]}}
        response = await get_async_task_status("task", user_id="u1")
        self.assertEqual(response.result, "actual report")
        self.loader.publish_async_task_result.assert_awaited_once()

    async def test_empty_success_result_is_not_fabricated(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            await get_async_task_status("task", user_id="u1")
        self.assertEqual(raised.exception.status_code, 502)
        self.loader.publish_async_task_result.assert_not_awaited()

    async def test_image_without_artifact_id_survives_delivery(self) -> None:
        for source in ["https://example.com/chart.png", "data:image/png;base64,YQ=="]:
            self.client.threads.get_state.return_value = {"values": {"messages": [{"type": "ai", "content": source}]}}
            response = await get_async_task_status("task", user_id="u1")
            self.assertEqual(response.visualization.src, source)
            self.assertEqual(self.loader.publish_async_task_result.await_args.kwargs["artifact"]["src"], source)

    async def test_all_failure_statuses_expose_error(self) -> None:
        for status, normalized in [("ERROR", "error"), ("timeout", "timeout"), ("canceled", "cancelled"), ("interrupted", "interrupted")]:
            self.client.runs.list.return_value = [{"status": status}]
            response = await get_async_task_status("task", user_id="u1")
            self.assertEqual(response.status, normalized)
            self.assertTrue(response.done)
            self.assertTrue(response.error)
            self.assertNotEqual(response.result, "图表已生成。")
