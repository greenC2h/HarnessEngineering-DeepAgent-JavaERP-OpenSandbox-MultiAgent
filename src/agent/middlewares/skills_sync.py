"""在 DeepAgents 读取技能元数据前完成沙箱技能同步。"""

from __future__ import annotations

import asyncio
from typing import Any

from deepagents.middleware.skills import SkillsMiddleware

from agent.backends.skill_sync import SandboxSkillSynchronizer


class SandboxSkillsMiddleware(SkillsMiddleware):
    """用支持沙箱同步的实现替换内置技能中间件。"""

    # DeepAgents 通过这个名称替换内置实现，同时保留原有提示词和渐进式加载行为。
    name = "SkillsMiddleware"

    def __init__(self, *, synchronizer: SandboxSkillSynchronizer, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._synchronizer = synchronizer

    async def abefore_agent(self, state: dict[str, Any], runtime: Any, config: Any) -> Any:
        """
        在用户代理锁内同步，并刷新当前线程的技能索引。
        """
        backend = getattr(self._backend, "default", self._backend)
        await asyncio.to_thread(self._synchronizer.sync, backend)
        # manifest 属于用户级状态，而元数据属于单个线程，不能沿用旧缓存。
        refreshed_state = dict(state)
        refreshed_state.pop("skills_metadata", None)
        refreshed_state.pop("skills_load_errors", None)
        update = await super().abefore_agent(refreshed_state, runtime, config)
        if update is not None:
            update.setdefault("skills_load_errors", [])
        return update
