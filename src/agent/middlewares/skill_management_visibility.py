"""按当前用户消息动态显示主 Agent 的技能管理工具。"""

from __future__ import annotations

import re
from typing import Any, Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse


SKILL_INTENT_PATTERN = re.compile(
    r"技能|\bskills?\b|github\.com/.+/tree/|"
    r"(?:安装|下载|分配|删除|移除|更新).{0,12}(?:技能|skill)|"
    r"(?:技能|skill).{0,12}(?:安装|下载|分配|删除|移除|更新)",
    re.IGNORECASE,
)


class SkillManagementVisibilityMiddleware(AgentMiddleware):
    """只在最近一轮消息涉及技能管理时向模型显示技能管理工具。"""

    name = "skill_management_visibility"

    def __init__(self, tools: list[Any]) -> None:
        """注册工具，并在模型调用前按用户意图过滤其可见性。"""
        self.tools = tools
        self._tool_names = {
            str(getattr(tool, "name", "")) for tool in tools
        }

    def _should_expose_tools(self, messages: list[Any]) -> bool:
        """判断最近一轮用户消息是否包含技能管理意图。"""
        for message in reversed(messages):
            role = getattr(message, "type", None)
            if role is None and isinstance(message, dict):
                role = message.get("role")
            if role not in {"human", "user"}:
                continue
            content = getattr(message, "content", None)
            if content is None and isinstance(message, dict):
                content = message.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    str(item.get("text", "")) if isinstance(item, dict) else str(item)
                    for item in content
                )
            return bool(SKILL_INTENT_PATTERN.search(str(content or "")))
        return False

    def _visible_tools(self, request: ModelRequest) -> list[Any]:
        """返回当前模型调用允许看到的工具。"""
        return [
            tool
            for tool in request.tools
            if str(getattr(tool, "name", "")) not in self._tool_names
        ]

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """同步模型调用路径的工具过滤。"""
        if self._should_expose_tools(request.messages):
            return handler(request)
        return handler(request.override(tools=self._visible_tools(request)))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Any],
    ) -> Any:
        """异步模型调用路径的工具过滤。"""
        if self._should_expose_tools(request.messages):
            return await handler(request)
        return await handler(request.override(tools=self._visible_tools(request)))
