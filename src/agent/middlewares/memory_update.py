"""在主 Agent 完成 ERP 对话后，自动维护用户近期查询记忆。"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

import yaml
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel

from agent.schema import UserPreferences


logger = logging.getLogger(__name__)

PREFERENCES_FILENAME = "preferences.md"
MAX_RECENT_QUERIES = 5
MAX_QUERY_LENGTH = 160
ERP_KEYWORDS = (
    "供应商", "物料", "采购", "订单", "价格", "库存", "交货", "交期", "成本", "预算", "图表", "可视化",
    "supplier", "part", "order", "price", "inventory", "chart", "visualization",
)


def preferences_file_path(user_id: str) -> str:
    """返回原始 StoreBackend 中当前用户的偏好文件 key。

    Agent 看到的 `/memories/` 是 CompositeBackend 的虚拟路由前缀；
    中间件直接操作原始 Store 时，必须使用去掉该前缀后的内部 key。
    """
    return f"/{user_id}/{PREFERENCES_FILENAME}"


def _message_text(message: Any) -> str:
    """将 LangChain 消息内容归一化为可供摘要模型读取的文本。"""
    content = getattr(message, "content", "")
    if isinstance(content, list):
        return "".join(
            str(item.get("text", "")) if isinstance(item, dict) else str(item)
            for item in content
        ).strip()
    return str(content or "").strip()


def _has_delegation(messages: list[Any]) -> bool:
    """判断本轮是否已由主 Agent 委派 ERP 子任务。"""
    for message in messages:
        for call in getattr(message, "tool_calls", []) or []:
            if isinstance(call, dict) and call.get("name") in {"task", "start_async_task"}:
                return True
    return False


def _last_user_message(messages: list[Any]) -> str | None:
    """返回最后一条有 ERP 意义的用户消息。"""
    for message in reversed(messages):
        if getattr(message, "type", None) not in {"human", "user"}:
            continue
        content = _message_text(message)
        normalized = content.lower().replace(" ", "")
        if not content:
            return None
        if any(keyword in normalized for keyword in ERP_KEYWORDS) or _has_delegation(messages):
            return content
        return None
    return None


def _last_ai_summary(messages: list[Any]) -> str:
    """返回最近一条非空助手文本，限制输入长度以控制摘要调用开销。"""
    for message in reversed(messages):
        if getattr(message, "type", None) != "ai":
            continue
        content = _message_text(message)
        if content:
            return content[:300]
    return ""


def _preferred_from_summary(value: Any) -> dict[str, Any]:
    """只接受摘要模型返回的对象，避免异常格式污染长期偏好。"""
    if not isinstance(value, dict):
        return {}
    return {
        str(key).strip(): item
        for key, item in value.items()
        if str(key).strip()
    }


async def _extract_memory_update(
    model: BaseChatModel,
    user_message: str,
    ai_summary: str,
) -> tuple[str, dict[str, Any]]:
    """从本轮对话提取近期查询及用户明确表达的开放偏好增量。"""
    prompt = f"""Extract long-term memory updates from this ERP procurement exchange.

Return only JSON: {{"query": "", "preferred": {{}}}}.
"query" is one concise ERP request summary in the user's language, at most 80
characters, with no invented facts. Use "" when this is not an ERP request.
"preferred" is an open object: extract only stable preferences that the user
explicitly states for future interactions. Keys are not predefined; use concise,
meaningful keys that fit the preference. Do not infer preferences from a one-time
request, business data, or the assistant response. When an existing preference
uses the same meaning, update that key or nested object instead of creating a
synonymous duplicate key. Return {{}} when there is no new explicit long-term
preference.

User message: {user_message}
Assistant response summary: {ai_summary}
"""
    try:
        response = await model.ainvoke(prompt)
        content = _message_text(response)
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end <= start:
            return "", {}
        value = json.loads(content[start : end + 1])
        if not isinstance(value, dict):
            return "", {}
        query = str(value.get("query", "")).strip()[:MAX_QUERY_LENGTH]
        return query, _preferred_from_summary(value.get("preferred", {}))
    except (json.JSONDecodeError, TypeError, ValueError):
        logger.warning("用户近期查询摘要格式无效，跳过本次记忆更新")
    except Exception:
        logger.warning("用户近期查询摘要失败，跳过本次记忆更新", exc_info=True)
    return "", {}


def _preferences_from_content(content: str) -> UserPreferences:
    """解析偏好 YAML；缺失、损坏或旧格式均回退为空偏好。"""
    try:
        raw_value = yaml.safe_load(content) or {}
    except yaml.YAMLError:
        logger.warning("用户偏好文件格式无效，将保留为空偏好并写入近期查询")
        raw_value = {}
    if not isinstance(raw_value, dict):
        raw_value = {}
    raw_queries = raw_value.get("recent_queries", [])
    recent_queries = [str(query).strip() for query in raw_queries if str(query).strip()] if isinstance(raw_queries, list) else []
    preferred = raw_value.get("preferred", {})
    return UserPreferences(
        recent_queries=recent_queries,
        preferred=dict(preferred) if isinstance(preferred, dict) else {},
    )


def _store_content(item: Any) -> str:
    """从 StoreBackend 文件项读取文本，兼容早期按行存储的格式。"""
    if item is None:
        return ""
    value = getattr(item, "value", item)
    if not isinstance(value, dict):
        return ""
    content = value.get("content", "")
    return "\n".join(str(line) for line in content) if isinstance(content, list) else str(content)


def _merge_recent_queries(preferences: UserPreferences, query: str) -> UserPreferences:
    """把新摘要置顶、去重并限制近期查询数量。"""
    merged = [query]
    normalized_queries = {query.casefold()}
    for existing_query in preferences.recent_queries:
        normalized = existing_query.strip()
        if normalized and normalized.casefold() not in normalized_queries:
            merged.append(normalized)
            normalized_queries.add(normalized.casefold())
    return UserPreferences(preferred=preferences.preferred, recent_queries=merged[:MAX_RECENT_QUERIES])


def _merge_preferred(
    preferences: UserPreferences,
    preference_updates: dict[str, Any],
) -> UserPreferences:
    """以本轮明确表达的开放键增量覆盖同名长期偏好。"""
    return UserPreferences(
        preferred={**preferences.preferred, **preference_updates},
        recent_queries=preferences.recent_queries,
    )


def _serialize_preferences(preferences: UserPreferences) -> str:
    """序列化稳定且精简的偏好文件内容。"""
    return yaml.safe_dump(
        {"preferred": preferences.preferred, "recent_queries": preferences.recent_queries},
        allow_unicode=True,
        sort_keys=False,
    )


def _store_value(content: str, item: Any) -> dict[str, str]:
    """构造 StoreBackend 兼容的文件值并保留首次创建时间。"""
    existing_value = getattr(item, "value", item) if item is not None else {}
    created_at = existing_value.get("created_at") if isinstance(existing_value, dict) else None
    now = datetime.now(timezone.utc).isoformat()
    return {"content": content, "encoding": "utf-8", "created_at": str(created_at or now), "modified_at": now}


class MemoryUpdateMiddleware(AgentMiddleware):
    """在每轮 ERP 回答结束后自动维护当前用户的长期偏好。"""

    def __init__(self, model: BaseChatModel) -> None:
        """保存专用于低成本查询摘要的模型。"""
        super().__init__()
        self._model = model

    async def update_state(
        self,
        state: Any,
        *,
        user_id: str,
        store: Any,
    ) -> None:
        """从已完成的 Agent 状态更新用户记忆，供 after-agent 钩子复用。"""
        state_values = state if isinstance(state, dict) else getattr(state, "values", {})
        messages = list(state_values.get("messages", [])) if isinstance(state_values, dict) else []
        if not user_id or store is None or not messages:
            return None
        user_message = _last_user_message(messages)
        if user_message is None:
            return None
        query, preference_updates = await _extract_memory_update(
            self._model,
            user_message,
            _last_ai_summary(messages),
        )
        # 摘要模型偶发返回空 query 时，仍保留已判定为 ERP 请求的原始消息，
        # 避免一次格式波动让近期查询记录永久缺失。
        if not query:
            query = user_message[:MAX_QUERY_LENGTH]
        if not query and not preference_updates:
            return None
        path = preferences_file_path(user_id)
        try:
            item = await store.aget((user_id,), path)
            preferences = _preferences_from_content(_store_content(item))
            updated_preferences = _merge_preferred(preferences, preference_updates)
            if query:
                updated_preferences = _merge_recent_queries(updated_preferences, query)
            await store.aput(
                (user_id,),
                path,
                _store_value(_serialize_preferences(updated_preferences), item),
                index=False,
            )
            logger.info(
                "已自动更新用户长期记忆：has_query=%s，preference_update_count=%d",
                bool(query),
                len(preference_updates),
            )
        except Exception:
            logger.warning("更新用户 %s 的近期查询失败", user_id, exc_info=True)
        return None

    async def aafter_agent(self, state: dict[str, Any], runtime: Any) -> None:
        """提取本轮查询摘要和明确偏好，并合并进 StoreBackend 偏好文件。"""
        context = getattr(runtime, "context", None)
        await self.update_state(
            state,
            user_id=str(getattr(context, "user_id", "") or ""),
            store=getattr(runtime, "store", None),
        )
