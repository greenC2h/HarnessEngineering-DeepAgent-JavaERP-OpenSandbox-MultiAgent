"""用户长期偏好自动更新的回归测试。"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.store.memory import InMemoryStore

from agent.middlewares.memory_update import (
    MAX_RECENT_QUERIES,
    MemoryUpdateMiddleware,
    _merge_preferred,
    _merge_recent_queries,
    _last_user_message,
    _preferences_from_content,
    preferences_file_path,
)
from agent.schema import ProcurementContext, UserPreferences


class ToolBindableFakeChatModel(FakeMessagesListChatModel):
    """支持 DeepAgents 工具绑定的最小测试模型。"""

    def bind_tools(self, tools, **kwargs):
        """测试中不执行工具，仅保留模型响应。"""
        return self


class UserPreferencesTests(unittest.TestCase):
    """覆盖偏好模型默认值和近期查询合并规则。"""

    def test_preferences_default_to_empty_collections(self) -> None:
        """新用户没有任何偏好文件时应使用空集合默认值。"""
        preferences = UserPreferences()

        self.assertEqual(preferences.preferred, {})
        self.assertEqual(preferences.recent_queries, [])

    def test_english_erp_query_is_not_filtered_by_greeting_fragments(self) -> None:
        """普通英文单词包含 hi 时，ERP 查询仍应进入近期查询。"""
        message = HumanMessage(content="show this inventory")

        self.assertEqual(_last_user_message([message]), "show this inventory")

    def test_recent_queries_preserve_preferences_and_deduplicate(self) -> None:
        """自动摘要只更新近期查询，保留手动维护的开放偏好对象。"""
        preferences = UserPreferences(
            preferred={"chart_type": "line", "currency": "CNY"},
            recent_queries=["库存趋势", "供应商价格对比", "库存趋势"],
        )

        updated = _merge_recent_queries(preferences, "库存趋势")

        self.assertEqual(updated.preferred, preferences.preferred)
        self.assertEqual(updated.recent_queries, ["库存趋势", "供应商价格对比"])

    def test_recent_queries_are_capped(self) -> None:
        """近期查询不能无限增长。"""
        preferences = UserPreferences(
            recent_queries=[f"查询 {index}" for index in range(MAX_RECENT_QUERIES + 2)]
        )

        updated = _merge_recent_queries(preferences, "最新查询")

        self.assertEqual(len(updated.recent_queries), MAX_RECENT_QUERIES)
        self.assertEqual(updated.recent_queries[0], "最新查询")

    def test_preferred_accepts_open_keys_and_overwrites_only_matching_key(self) -> None:
        """自动提炼的偏好不受预定义字段限制，并保留无关已有键。"""
        preferences = UserPreferences(
            preferred={"chart_type": "bar", "report_density": "compact"},
        )

        updated = _merge_preferred(
            preferences,
            {"chart_type": "line", "supplier_sorting": "delivery_date"},
        )

        self.assertEqual(
            updated.preferred,
            {
                "chart_type": "line",
                "report_density": "compact",
                "supplier_sorting": "delivery_date",
            },
        )


class MemoryUpdateMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    """验证中间件只在有意义的 ERP 对话后写入 StoreBackend。"""

    async def test_updates_recent_query_without_overwriting_preferred(self) -> None:
        """摘要结果应合并到 Store 文件，并保留人工维护的偏好。"""
        store = SimpleNamespace(
            aget=AsyncMock(
                return_value=SimpleNamespace(
                    value={
                        "content": "preferred:\n  chart_type: line\nrecent_queries:\n  - 供应商报价\n",
                        "encoding": "utf-8",
                        "created_at": "2026-01-01T00:00:00+00:00",
                    }
                )
            ),
            aput=AsyncMock(),
        )
        summary_model = SimpleNamespace(
            ainvoke=AsyncMock(
                return_value=AIMessage(
                    content=(
                        '{"query": "库存预警趋势图", '
                        '"preferred": {"report_density": "compact"}}'
                    )
                )
            )
        )
        runtime = SimpleNamespace(
            context=ProcurementContext(user_id="u1", username="张三"),
            store=store,
        )
        middleware = MemoryUpdateMiddleware(summary_model)

        await middleware.aafter_agent(
            {
                "messages": [
                    HumanMessage(content="请生成库存预警趋势图"),
                    AIMessage(content="已提交图表任务。"),
                ]
            },
            runtime,
        )

        summary_model.ainvoke.assert_awaited_once()
        store.aget.assert_awaited_once_with(("u1",), preferences_file_path("u1"))
        store.aput.assert_awaited_once()
        namespace, path, value = store.aput.await_args.args
        self.assertEqual(namespace, ("u1",))
        self.assertEqual(path, preferences_file_path("u1"))
        self.assertFalse(store.aput.await_args.kwargs["index"])
        preferences = _preferences_from_content(value["content"])
        self.assertEqual(
            preferences.preferred,
            {"chart_type": "line", "report_density": "compact"},
        )
        self.assertEqual(preferences.recent_queries, ["库存预警趋势图", "供应商报价"])
        self.assertEqual(value["created_at"], "2026-01-01T00:00:00+00:00")

    async def test_skips_greetings_without_calling_summary_model(self) -> None:
        """普通问候不应消耗摘要模型或创建偏好文件。"""
        store = SimpleNamespace(aget=AsyncMock(), aput=AsyncMock())
        summary_model = SimpleNamespace(ainvoke=AsyncMock())
        runtime = SimpleNamespace(
            context=ProcurementContext(user_id="u1", username="张三"),
            store=store,
        )

        await MemoryUpdateMiddleware(summary_model).aafter_agent(
            {"messages": [HumanMessage(content="你好"), AIMessage(content="你好，有什么可以帮你？")]},
            runtime,
        )

        summary_model.ainvoke.assert_not_awaited()
        store.aget.assert_not_awaited()

    async def test_uses_user_message_when_summary_model_returns_empty_query(self) -> None:
        """摘要格式波动不能让已经判定的 ERP 查询丢失。"""
        store = SimpleNamespace(aget=AsyncMock(return_value=None), aput=AsyncMock())
        summary_model = SimpleNamespace(
            ainvoke=AsyncMock(return_value=AIMessage(content='{"query": "", "preferred": {}}'))
        )
        runtime = SimpleNamespace(
            context=ProcurementContext(user_id="u1", username="张三"),
            store=store,
        )

        await MemoryUpdateMiddleware(summary_model).aafter_agent(
            {
                "messages": [
                    HumanMessage(content="请查询库存"),
                    AIMessage(content="当前没有库存查询工具。"),
                ]
            },
            runtime,
        )

        value = store.aput.await_args.args[2]
        preferences = _preferences_from_content(value["content"])
        self.assertEqual(preferences.recent_queries, ["请查询库存"])

    async def test_langgraph_after_agent_hook_persists_memory(self) -> None:
        """编译后的 LangGraph 必须执行异步 after_agent 钩子并传入 Store。"""
        store = InMemoryStore()
        agent_model = ToolBindableFakeChatModel(responses=[AIMessage(content="已完成库存查询。")])
        summary_model = FakeMessagesListChatModel(
            responses=[
                AIMessage(
                    content=(
                        '{"query": "库存查询", '
                        '"preferred": {"table_style": "compact"}}'
                    )
                )
            ]
        )
        agent = create_agent(
            agent_model,
            middleware=[MemoryUpdateMiddleware(summary_model)],
            store=store,
            context_schema=ProcurementContext,
        )

        await agent.ainvoke(
            {"messages": [{"role": "user", "content": "请查询库存"}]},
            context=ProcurementContext(user_id="runtime-test", username="测试用户"),
        )

        item = await store.aget(
            ("runtime-test",),
            preferences_file_path("runtime-test"),
        )
        self.assertIsNotNone(item)
        preferences = _preferences_from_content(item.value["content"])
        self.assertEqual(preferences.recent_queries, ["库存查询"])
        self.assertEqual(preferences.preferred, {"table_style": "compact"})

    async def test_deep_agent_after_agent_hook_persists_memory(self) -> None:
        """DeepAgents 主图也必须执行用户提供的 after_agent 中间件。"""
        store = InMemoryStore()
        agent_model = ToolBindableFakeChatModel(responses=[AIMessage(content="已完成库存查询。")])
        summary_model = FakeMessagesListChatModel(
            responses=[AIMessage(content='{"query": "库存查询", "preferred": {}}')]
        )
        agent = create_deep_agent(
            model=agent_model,
            middleware=[MemoryUpdateMiddleware(summary_model)],
            store=store,
            context_schema=ProcurementContext,
        )

        await agent.ainvoke(
            {"messages": [{"role": "user", "content": "请查询库存"}]},
            context=ProcurementContext(user_id="deep-agent-test", username="测试用户"),
        )

        item = await store.aget(
            ("deep-agent-test",),
            preferences_file_path("deep-agent-test"),
        )
        self.assertIsNotNone(item)
        preferences = _preferences_from_content(item.value["content"])
        self.assertEqual(preferences.recent_queries, ["库存查询"])

    async def test_deep_agent_stream_after_agent_hook_persists_memory(self) -> None:
        """API 使用的 v2 消息和值流也必须等待 after_agent 完成。"""
        store = InMemoryStore()
        agent = create_deep_agent(
            model=ToolBindableFakeChatModel(responses=[AIMessage(content="已完成库存查询。")]),
            middleware=[
                MemoryUpdateMiddleware(
                    FakeMessagesListChatModel(
                        responses=[AIMessage(content='{"query": "库存查询", "preferred": {}}')]
                    )
                )
            ],
            store=store,
            context_schema=ProcurementContext,
        )

        async for _ in agent.astream(
            {"messages": [{"role": "user", "content": "请查询库存"}]},
            context=ProcurementContext(user_id="stream-test", username="测试用户"),
            stream_mode=["messages", "values"],
            subgraphs=True,
            version="v2",
        ):
            pass

        item = await store.aget(
            ("stream-test",),
            preferences_file_path("stream-test"),
        )
        self.assertIsNotNone(item)
        preferences = _preferences_from_content(item.value["content"])
        self.assertEqual(preferences.recent_queries, ["库存查询"])

    async def test_composite_backend_uses_store_internal_path(self) -> None:
        """生产路由下中间件必须写入模型可读的 Store 内部 key。"""
        store = InMemoryStore()
        backend = CompositeBackend(
            default=StateBackend(),
            routes={
                "/memories/": StoreBackend(
                    namespace=lambda _runtime: ("composite-test",),
                    store=store,
                )
            },
        )
        agent = create_deep_agent(
            model=ToolBindableFakeChatModel(responses=[AIMessage(content="已完成库存查询。")]),
            middleware=[
                MemoryUpdateMiddleware(
                    FakeMessagesListChatModel(
                        responses=[AIMessage(content='{"query": "库存查询", "preferred": {}}')]
                    )
                )
            ],
            backend=backend,
            store=store,
            context_schema=ProcurementContext,
        )

        await agent.ainvoke(
            {"messages": [{"role": "user", "content": "请查询库存"}]},
            context=ProcurementContext(user_id="composite-test", username="测试用户"),
        )

        item = await store.aget(
            ("composite-test",),
            preferences_file_path("composite-test"),
        )
        legacy_item = await store.aget(
            ("composite-test",),
            "/memories/composite-test/preferences.md",
        )
        self.assertIsNotNone(item)
        self.assertIsNone(legacy_item)
        preferences = _preferences_from_content(item.value["content"])
        self.assertEqual(preferences.recent_queries, ["库存查询"])

    async def test_update_state_accepts_checkpoint_snapshot(self) -> None:
        """checkpoint snapshot 应与 middleware state 使用相同的更新逻辑。"""
        store = SimpleNamespace(aget=AsyncMock(return_value=None), aput=AsyncMock())
        summary_model = SimpleNamespace(
            ainvoke=AsyncMock(return_value=AIMessage(content='{"query": "订单查询", "preferred": {}}'))
        )

        await MemoryUpdateMiddleware(summary_model).update_state(
            SimpleNamespace(
                values={
                    "messages": [
                        HumanMessage(content="请查询采购订单"),
                        AIMessage(content="查询完成。"),
                    ]
                }
            ),
            user_id="snapshot-test",
            store=store,
        )

        self.assertEqual(
            _preferences_from_content(store.aput.await_args.args[2]["content"]).recent_queries,
            ["订单查询"],
        )

    def test_invalid_preference_content_defaults_to_empty_preferences(self) -> None:
        """损坏的 YAML 不得阻止后续自动记忆更新。"""
        with self.assertLogs("agent.middlewares.memory_update", level="WARNING"):
            preferences = _preferences_from_content("preferred: [")

        self.assertEqual(preferences, UserPreferences())


if __name__ == "__main__":
    unittest.main()
