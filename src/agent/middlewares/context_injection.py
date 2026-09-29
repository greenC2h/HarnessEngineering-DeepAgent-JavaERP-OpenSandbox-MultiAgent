"""将运行时用户身份注入主 Agent 的系统提示词。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage


class ContextInjectionMiddleware(AgentMiddleware):
    """将 ``runtime.context`` 中的用户身份写入每次主模型调用的系统提示词。"""

    name = "context_injection"

    @staticmethod
    def _context_notice(context: Any) -> str | None:
        """构造当前调用可见的用户身份说明，缺失身份时跳过注入。"""
        user_id = str(getattr(context, "user_id", "") or "").strip()
        if not user_id:
            return None
        username = str(getattr(context, "username", "") or user_id).strip()
        return (
            "当前运行时用户信息：\n"
            f"- user_id: {user_id}\n"
            f"- username: {username}\n"
            f"- 偏好文件: /memories/{user_id}/preferences.md\n"
            "处理本轮任务前先读取该偏好文件；recent_queries 由系统自动维护。"
        )

    def _inject_context(self, request: ModelRequest) -> ModelRequest:
        """返回包含运行时身份信息的模型请求，不修改持久化消息历史。"""
        runtime = request.runtime
        notice = self._context_notice(getattr(runtime, "context", None))
        if notice is None:
            return request
        system_message = request.system_message or SystemMessage(content="")
        content = system_message.content
        if isinstance(content, str):
            injected_content = f"{content}\n\n{notice}".strip()
        else:
            injected_content = [*content, {"type": "text", "text": notice}]
        return request.override(
            system_message=SystemMessage(content=injected_content),
        )

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """在同步模型调用前注入用户上下文。"""
        return handler(self._inject_context(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """在异步模型调用前注入用户上下文。"""
        return await handler(self._inject_context(request))
