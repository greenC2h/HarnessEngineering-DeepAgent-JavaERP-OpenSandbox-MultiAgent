"""本地技能下载后分配、查询和删除行为的单元测试。"""

from __future__ import annotations

import json
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agent.middlewares.skill_management_visibility import (
    SkillManagementVisibilityMiddleware,
)
from agent.tools.skill_tools import _skill_management_script

_assign_skill = _skill_management_script._assign_skill
_delete_subagent_skill = _skill_management_script._delete_subagent_skill
_ensure_skill_directories = _skill_management_script._ensure_skill_directories
_list_subagent_skills = _skill_management_script._list_subagent_skills
_update_subagent_skill = _skill_management_script._update_subagent_skill
_download_skill = _skill_management_script._download_skill


SUBAGENT_NAMES = {"procurement_order"}


def write_standard_skill(skill_directory: Path, name: str, description: str) -> None:
    """创建具有必要元信息的最小测试技能。"""
    skill_directory.mkdir()
    (skill_directory / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n# {name}\n",
        encoding="utf-8",
    )
    (skill_directory / "metadata.json").write_text(
        f'{{"name": "{name}", "description": "{description}"}}',
        encoding="utf-8",
    )


class SkillManagementTests(unittest.TestCase):
    """验证主 Agent 暂存技能和子 Agent 已分配技能严格隔离。"""

    def test_assignment_moves_skill_and_listing_exposes_metadata_only(self) -> None:
        """分配后主目录不保留技能，查询只返回标题和描述。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            skills_root = Path(temporary_directory)
            _ensure_skill_directories(skills_root, SUBAGENT_NAMES)
            source_directory = skills_root / "main" / "inventory-guide"
            write_standard_skill(source_directory, "库存指引", "用于检查库存阈值。")
            (source_directory / "details.md").write_text("内部步骤", encoding="utf-8")

            target_directory = _assign_skill(
                skills_root,
                "inventory-guide",
                "procurement_order",
                SUBAGENT_NAMES,
            )
            result = _list_subagent_skills(
                skills_root,
                "procurement_order",
                SUBAGENT_NAMES,
            )

            self.assertFalse(source_directory.exists())
            self.assertTrue(target_directory.is_dir())
            self.assertEqual(
                result,
                {
                    "procurement_order": [
                        {
                            "skill_name": "inventory-guide",
                            "name": "库存指引",
                            "description": "用于检查库存阈值。",
                        }
                    ]
                },
            )

    def test_assignment_to_main_keeps_skill_in_main_directory(self) -> None:
        """目标为 main 时应完成校验并保留主 Agent 技能目录。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            skills_root = Path(temporary_directory)
            _ensure_skill_directories(skills_root, SUBAGENT_NAMES)
            source_directory = skills_root / "main" / "main-guide"
            write_standard_skill(source_directory, "主 Agent 指引", "主 Agent 专用技能。")

            management_tools = _skill_management_script.create_skill_management_tools(
                skills_root,
                SUBAGENT_NAMES,
            )
            result = management_tools[1].invoke(
                {"skill_name": "main-guide", "subagent_name": "main"}
            )

            self.assertIn("已安装到主 Agent", result)
            self.assertTrue(source_directory.is_dir())

    def test_delete_removes_only_the_selected_subagent_skill(self) -> None:
        """删除已分配技能不会影响其他子 Agent 目录或主 Agent 暂存目录。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            skills_root = Path(temporary_directory)
            _ensure_skill_directories(skills_root, SUBAGENT_NAMES)
            skill_directory = skills_root / "subagents" / "procurement_order" / "obsolete-guide"
            write_standard_skill(skill_directory, "旧指引", "待移除。")

            _delete_subagent_skill(
                skills_root,
                "obsolete-guide",
                "procurement_order",
                SUBAGENT_NAMES,
            )

            self.assertFalse(skill_directory.exists())
            self.assertTrue((skills_root / "main").is_dir())

    def test_rejects_unknown_subagent(self) -> None:
        """不能将技能放入未注册的子 Agent 目录。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            skills_root = Path(temporary_directory)
            _ensure_skill_directories(skills_root, SUBAGENT_NAMES)

            with self.assertRaisesRegex(ValueError, "未知 Agent"):
                _assign_skill(
                    skills_root,
                    "inventory-guide",
                    "unknown-agent",
                    SUBAGENT_NAMES,
                )

    def test_update_restores_old_skill_when_download_fails(self) -> None:
        """更新失败时应恢复目标子 Agent 原本可用的技能目录。"""
        with tempfile.TemporaryDirectory() as temporary_directory:
            skills_root = Path(temporary_directory)
            _ensure_skill_directories(skills_root, SUBAGENT_NAMES)
            skill_directory = skills_root / "subagents" / "procurement_order" / "inventory-guide"
            write_standard_skill(skill_directory, "旧库存指引", "旧版本说明。")

            with patch.object(
                _skill_management_script,
                "_download_skill",
                side_effect=ValueError("下载失败"),
            ):
                with self.assertRaisesRegex(ValueError, "下载失败"):
                    _update_subagent_skill(
                        skills_root,
                        "https://example.com/inventory-guide.zip",
                        "procurement_order",
                        SUBAGENT_NAMES,
                    )

            self.assertTrue(skill_directory.is_dir())
            self.assertIn("旧库存指引", (skill_directory / "SKILL.md").read_text(encoding="utf-8"))

    def test_downloads_github_tree_skill_and_generates_metadata(self) -> None:
        """GitHub tree 链接应从仓库 ZIP 提取目标目录并生成本地元信息。"""
        archive_content = BytesIO()
        with zipfile.ZipFile(archive_content, "w") as archive:
            archive.writestr(
                "anthropics-skills-test/skills/example-skill/SKILL.md",
                "---\nname: 示例技能\ndescription: GitHub 来源技能。\n---\n\n# 示例技能\n",
            )

        with tempfile.TemporaryDirectory() as temporary_directory:
            skills_root = Path(temporary_directory)
            _ensure_skill_directories(skills_root, SUBAGENT_NAMES)
            with patch.object(
                _skill_management_script.urllib.request,
                "urlopen",
                return_value=BytesIO(archive_content.getvalue()),
            ):
                result = _download_skill(
                    skills_root,
                    "https://github.com/anthropics/skills/tree/main/skills/example-skill",
                )

            installed_directory = skills_root / "main" / "example-skill"
            self.assertEqual(result["skill_name"], "example-skill")
            self.assertTrue(installed_directory.is_dir())
            self.assertEqual(
                json.loads((installed_directory / "metadata.json").read_text(encoding="utf-8")),
                {"name": "示例技能", "description": "GitHub 来源技能。"},
            )


class SkillManagementVisibilityTests(unittest.IsolatedAsyncioTestCase):
    """验证普通对话不会携带技能管理工具 schema。"""

    def setUp(self) -> None:
        self.skill_tool = SimpleNamespace(name="download_skill")
        self.common_tool = SimpleNamespace(name="web_search")
        self.middleware = SkillManagementVisibilityMiddleware([self.skill_tool])

    def test_hides_skill_tools_for_normal_message(self) -> None:
        request = self._request("查询供应商列表")
        captured = []
        self.middleware.wrap_model_call(request, lambda value: captured.append(value) or value)

        self.assertEqual(captured[0].tools, [self.common_tool])

    def test_keeps_skill_tools_for_skill_request(self) -> None:
        request = self._request("请安装这个 GitHub skill")
        captured = []
        self.middleware.wrap_model_call(request, lambda value: captured.append(value) or value)

        self.assertEqual(captured[0], request)

    async def test_async_path_hides_skill_tools(self) -> None:
        request = self._request("查询订单状态")

        async def handler(value: SimpleNamespace) -> SimpleNamespace:
            return value

        result = await self.middleware.awrap_model_call(request, handler)

        self.assertEqual(result.tools, [self.common_tool])

    def _request(self, content: str) -> SimpleNamespace:
        request = SimpleNamespace(
            messages=[{"role": "user", "content": content}],
            tools=[self.common_tool, self.skill_tool],
        )
        request.override = lambda **kwargs: SimpleNamespace(
            messages=request.messages,
            tools=kwargs["tools"],
        )
        return request
