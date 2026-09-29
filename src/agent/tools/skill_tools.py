"""将 skill-management 技能脚本注册为主 Agent 可调用工具。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


SKILL_MANAGEMENT_SCRIPT = (
    Path(__file__).parent.parent
    / "skills"
    / "main"
    / "skill-management"
    / "scripts"
    / "skill_management.py"
)


def _load_skill_management_script() -> ModuleType:
    """加载技能目录中的管理实现，避免把技能逻辑复制到工具模块。"""
    specification = importlib.util.spec_from_file_location(
        "agent_skill_management_script",
        SKILL_MANAGEMENT_SCRIPT,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("无法加载 skill-management 脚本")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


_skill_management_script = _load_skill_management_script()
create_skill_management_tools = _skill_management_script.create_skill_management_tools
