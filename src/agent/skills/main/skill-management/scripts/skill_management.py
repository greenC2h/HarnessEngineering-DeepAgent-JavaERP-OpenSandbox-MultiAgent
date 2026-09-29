"""供 skill-management 技能调用的本地下载、分配、查询和删除实现。"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, quote, unquote, urlparse

import yaml


SKILL_FILE_NAME = "SKILL.md"
METADATA_FILE_NAME = "metadata.json"
MAIN_SKILLS_DIRECTORY = "main"
SUBAGENTS_DIRECTORY = "subagents"
PACKAGE_SUFFIXES = (".zip", ".tar", ".tar.gz", ".tar.bz2", ".tar.xz", ".tgz")
SKILL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
REQUIRED_SKILL_FILES = (SKILL_FILE_NAME, METADATA_FILE_NAME)


def create_skill_management_tools(
    skills_root: Path,
    subagent_names: set[str],
    *,
    sandbox_backend: Any = None,
    synchronize: Callable[[], None] | None = None,
) -> list[Any]:
    """
    创建沙箱优先的技能管理工具；省略 backend 仅供本地测试和管理兼容。

    Args:
        skills_root: 主 Agent 和子 Agent 技能目录的本地根目录。
        subagent_names: 允许接收技能的子 Agent 名称集合。
        sandbox_backend: 运行时沙箱代理；Agent 调用必须传入以隔离下载和执行。

    Returns:
        供主 Agent 使用的 LangChain 工具列表。
    """
    from langchain_core.tools import tool

    if sandbox_backend is not None:
        from agent.tools.sandbox_skill_management import create_sandbox_skill_tools

        return create_sandbox_skill_tools(
            skills_root,
            subagent_names,
            sandbox_backend,
            synchronize=synchronize,
        )

    root = skills_root.resolve()
    _ensure_skill_directories(root, subagent_names)

    @tool
    async def download_skill(skill_url: str) -> str:
        """
        下载 ZIP 或 GitHub 目录链接指向的技能到主 Agent 暂存目录。

        下载后的技能仅属于主 Agent；完成校验后应调用 assign_skill 分配给子
        Agent，分配会移走该目录。外部技能只需提供含 name、description 的 SKILL.md；
        缺失的 metadata.json 会在本地自动生成。
        """
        try:
            result = await asyncio.to_thread(_download_skill, root, skill_url)
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            return f"下载技能失败: {error}"
        return json.dumps(result, ensure_ascii=False)

    @tool
    def assign_skill(skill_name: str, subagent_name: str) -> str:
        """
        将技能安装到主 Agent 或分配给一个子 Agent。

        Args:
            skill_name: 已通过 download_skill 下载的技能目录名。
            subagent_name: 目标名称。使用 ``main`` 安装到主 Agent，或填写子 Agent 名称。
        """
        try:
            target = _assign_skill(root, skill_name, subagent_name, subagent_names)
        except (OSError, ValueError) as error:
            return f"分配技能失败: {error}"
        if subagent_name == MAIN_SKILLS_DIRECTORY:
            return f"技能 '{skill_name}' 已安装到主 Agent。路径: {target}"
        return f"技能 '{skill_name}' 已分配给 '{subagent_name}'，主 Agent 不再持有该技能。路径: {target}"

    @tool
    def list_subagent_skills(subagent_name: str | None = None) -> str:
        """
        查询子 Agent 已分配技能的名称和描述，不读取或返回技能正文。

        传入 subagent_name 时只查询该子 Agent；省略时查询所有子 Agent。
        """
        try:
            result = _list_subagent_skills(root, subagent_name, subagent_names)
        except (OSError, ValueError) as error:
            return f"查询技能失败: {error}"
        return json.dumps(result, ensure_ascii=False)

    @tool
    def delete_subagent_skill(skill_name: str, subagent_name: str) -> str:
        """
        删除一个已分配给子 Agent 的技能目录及其中全部文件。

        Args:
            skill_name: 要删除的技能目录名。
            subagent_name: 当前持有该技能的子 Agent 名称。
        """
        try:
            _delete_subagent_skill(root, skill_name, subagent_name, subagent_names)
        except (OSError, ValueError) as error:
            return f"删除技能失败: {error}"
        return f"已删除子 Agent '{subagent_name}' 的技能 '{skill_name}'。"

    @tool
    async def update_subagent_skill(skill_url: str, subagent_name: str) -> str:
        """
        用 ZIP 链接更新子 Agent 已持有的同名技能，并在失败时恢复旧版本。

        ZIP 链接的 slug 或文件名必须与目标技能目录名相同。更新完成后，新版本
        直接位于子 Agent 的独立目录，主 Agent 不会持有该技能副本。
        """
        try:
            result = await asyncio.to_thread(
                _update_subagent_skill,
                root,
                skill_url,
                subagent_name,
                subagent_names,
            )
        except (OSError, ValueError, zipfile.BadZipFile) as error:
            return f"更新技能失败: {error}"
        return json.dumps(result, ensure_ascii=False)

    return [
        download_skill,
        assign_skill,
        list_subagent_skills,
        delete_subagent_skill,
        update_subagent_skill,
    ]


def _ensure_skill_directories(skills_root: Path, subagent_names: set[str]) -> None:
    """创建受限技能目录和每个子 Agent 的独立目录。"""
    (skills_root / MAIN_SKILLS_DIRECTORY).mkdir(parents=True, exist_ok=True)
    for subagent_name in subagent_names:
        (skills_root / SUBAGENTS_DIRECTORY / subagent_name).mkdir(parents=True, exist_ok=True)


def _skill_directory(parent: Path, skill_name: str) -> Path:
    """验证技能名并返回保证位于 parent 下的目录路径。"""
    if not SKILL_NAME_PATTERN.fullmatch(skill_name):
        raise ValueError("技能名只能包含字母、数字、连字符和下划线，且长度不超过 64")
    if skill_name.casefold() == "skill-management":
        raise ValueError("skill-management 是受保护的管理技能")
    return parent / skill_name


def _validate_target_name(target_name: str, subagent_names: set[str]) -> None:
    """确认目标是主 Agent 或已注册的子 Agent。"""
    if target_name == MAIN_SKILLS_DIRECTORY or target_name in subagent_names:
        return
    available = ", ".join([MAIN_SKILLS_DIRECTORY, *sorted(subagent_names)])
    raise ValueError(f"未知 Agent '{target_name}'，可用值: {available}")


def _validate_subagent_name(subagent_name: str, subagent_names: set[str]) -> None:
    """确认删除或更新目标是已注册的子 Agent，而不是主 Agent。"""
    if subagent_name not in subagent_names:
        available = ", ".join(sorted(subagent_names))
        raise ValueError(f"未知子 Agent '{subagent_name}'，可用值: {available}")


def _parse_skill_metadata(skill_directory: Path) -> dict[str, str]:
    """校验必要元信息，并返回仅供索引使用的元数据。"""
    missing_files = [
        file_name
        for file_name in REQUIRED_SKILL_FILES
        if not (skill_directory / file_name).is_file()
    ]
    if missing_files:
        raise ValueError(f"技能目录缺少: {', '.join(missing_files)}")

    skill_file = skill_directory / SKILL_FILE_NAME
    content = skill_file.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise ValueError("SKILL.md 缺少 YAML frontmatter")
    frontmatter_end = content.find("\n---", 4)
    if frontmatter_end == -1:
        raise ValueError("SKILL.md 的 YAML frontmatter 未闭合")
    metadata = yaml.safe_load(content[4:frontmatter_end])
    if not isinstance(metadata, dict):
        raise ValueError("SKILL.md frontmatter 必须是映射")
    name = metadata.get("name")
    description = metadata.get("description")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("SKILL.md frontmatter 缺少 name")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("SKILL.md frontmatter 缺少 description")

    try:
        json_metadata = json.loads(
            (skill_directory / METADATA_FILE_NAME).read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as error:
        raise ValueError("metadata.json 必须是合法 JSON") from error
    if not isinstance(json_metadata, dict):
        raise ValueError("metadata.json 必须是对象")
    if json_metadata.get("name") != name.strip() or json_metadata.get("description") != description.strip():
        raise ValueError("metadata.json 的 name 和 description 必须与 SKILL.md 一致")
    return {"name": name.strip(), "description": description.strip()}


def _resolve_skill_source(skill_url: str) -> tuple[str, str, Path | None]:
    """将普通 ZIP 或 GitHub tree 链接解析为下载地址和技能相对目录。"""
    parsed_url = urlparse(skill_url)
    if parsed_url.scheme not in {"http", "https"}:
        raise ValueError("技能链接必须使用 http 或 https")
    slug = parse_qs(parsed_url.query).get("slug", [""])[0]
    path_parts = [unquote(part) for part in parsed_url.path.split("/") if part]
    if parsed_url.netloc.lower() == "github.com" and len(path_parts) >= 5 and path_parts[2] == "tree":
        owner, repository, _, ref, *skill_path = path_parts
        if not skill_path or any(
            part in {"", ".", ".."} or any(char in part for char in "/\\:")
            for part in [owner, repository, *skill_path]
        ):
            raise ValueError("GitHub tree 链接必须指向具体技能目录")
        candidate = skill_path[-1]
        archive_url = (
            f"https://codeload.github.com/{owner}/{repository}/zip/refs/heads/"
            f"{quote(ref, safe='')}"
        )
        _skill_directory(Path("."), candidate)
        return candidate, archive_url, Path(*skill_path)

    candidate = slug or Path(parsed_url.path).stem
    _skill_directory(Path("."), candidate)
    return candidate, skill_url, None


def _download_skill(skills_root: Path, skill_url: str) -> dict[str, Any]:
    """下载、定位、校验技能并清理所有临时压缩包。"""
    skill_name, archive_url, source_path = _resolve_skill_source(skill_url)
    main_directory = skills_root / MAIN_SKILLS_DIRECTORY
    target_directory = _skill_directory(main_directory, skill_name)
    if target_directory.exists():
        raise ValueError(f"主 Agent 已存在技能 '{skill_name}'，请先分配或删除后再下载")

    try:
        with tempfile.TemporaryDirectory(dir=main_directory) as temporary_name:
            temporary_directory = Path(temporary_name)
            archive_path = temporary_directory / "skill.zip"
            request = urllib.request.Request(archive_url, headers={"User-Agent": "MyAgent-skill-installer"})
            with urllib.request.urlopen(request, timeout=30) as response:
                content = response.read(32 * 1024 * 1024 + 1)
                if len(content) > 32 * 1024 * 1024:
                    raise ValueError("技能下载包超过 32 MiB 限制")
                archive_path.write_bytes(content)

            with zipfile.ZipFile(archive_path) as archive:
                _validate_archive_members(archive)
                extract_directory = temporary_directory / "extracted"
                archive.extractall(extract_directory)

            source_directory = _find_skill_directory(extract_directory, source_path)
            _ensure_skill_metadata(source_directory)
            metadata = _parse_skill_metadata(source_directory)
            shutil.move(str(source_directory), target_directory)
    finally:
        # TemporaryDirectory 会删除本次下载包；这里再清理旧版本可能遗留的压缩包。
        _cleanup_packages(main_directory)
    return {
        "skill_name": skill_name,
        "title": metadata["name"],
        "description": metadata["description"],
        "path": f"/skills/main/{skill_name}",
    }


def _validate_archive_members(archive: zipfile.ZipFile) -> None:
    """拒绝路径穿越和符号链接，避免 ZIP 解压覆盖技能根目录以外的文件。"""
    members = archive.infolist()
    if len(members) > 2048 or sum(member.file_size for member in members) > 32 * 1024 * 1024:
        raise ValueError("技能解压内容超过文件数或大小限制")
    for member in members:
        member_path = Path(member.filename)
        if member_path.is_absolute() or ".." in member_path.parts or "\\" in member.filename or ":" in member.filename:
            raise ValueError("ZIP 包包含不安全的路径")
        is_symbolic_link = (member.external_attr >> 16) & 0o170000 == 0o120000
        if is_symbolic_link:
            raise ValueError("ZIP 包不能包含符号链接")


def _find_skill_directory(extract_directory: Path, source_path: Path | None) -> Path:
    """定位 ZIP 根目录、包装目录或 GitHub tree 链接指定的技能目录。"""
    if source_path is not None:
        roots = [path for path in extract_directory.iterdir() if path.is_dir()]
        if len(roots) != 1:
            raise ValueError("GitHub 仓库压缩包结构无法识别")
        candidate = roots[0] / source_path
        if not candidate.is_dir():
            raise ValueError(f"GitHub 链接中的技能目录不存在: {source_path.as_posix()}")
        return candidate
    if (extract_directory / SKILL_FILE_NAME).is_file():
        return extract_directory
    children = [path for path in extract_directory.iterdir() if path.is_dir()]
    candidates = [path for path in children if (path / SKILL_FILE_NAME).is_file()]
    if len(candidates) != 1:
        raise ValueError("ZIP 包必须在根目录或唯一的顶层目录中包含 SKILL.md")
    return candidates[0]


def _ensure_skill_metadata(skill_directory: Path) -> None:
    """依据 SKILL.md frontmatter 为外部技能补齐本地索引元信息。"""
    metadata_path = skill_directory / METADATA_FILE_NAME
    if metadata_path.exists():
        return
    skill_file = skill_directory / SKILL_FILE_NAME
    if not skill_file.is_file():
        raise ValueError("技能目录缺少 SKILL.md")
    content = skill_file.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        raise ValueError("SKILL.md 缺少 YAML frontmatter")
    frontmatter_end = content.find("\n---", 4)
    if frontmatter_end == -1:
        raise ValueError("SKILL.md 的 YAML frontmatter 未闭合")
    frontmatter = yaml.safe_load(content[4:frontmatter_end])
    if not isinstance(frontmatter, dict):
        raise ValueError("SKILL.md frontmatter 必须是映射")
    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not isinstance(name, str) or not name.strip() or not isinstance(description, str) or not description.strip():
        raise ValueError("SKILL.md frontmatter 必须包含 name 和 description")
    metadata_path.write_text(
        json.dumps({"name": name.strip(), "description": description.strip()}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _assign_skill(
    skills_root: Path,
    skill_name: str,
    subagent_name: str,
    subagent_names: set[str],
) -> Path:
    """将已校验的技能保留在主 Agent 或移动到目标子 Agent 目录。"""
    _validate_target_name(subagent_name, subagent_names)
    source_directory = _skill_directory(skills_root / MAIN_SKILLS_DIRECTORY, skill_name)
    _parse_skill_metadata(source_directory)
    if subagent_name == MAIN_SKILLS_DIRECTORY:
        _cleanup_packages(skills_root / MAIN_SKILLS_DIRECTORY)
        return source_directory

    target_directory = _skill_directory(
        skills_root / SUBAGENTS_DIRECTORY / subagent_name,
        skill_name,
    )
    if not source_directory.is_dir():
        raise ValueError(f"主 Agent 不存在技能 '{skill_name}'")
    if target_directory.exists():
        raise ValueError(f"子 Agent '{subagent_name}' 已存在技能 '{skill_name}'")
    shutil.move(str(source_directory), target_directory)
    _cleanup_packages(skills_root / MAIN_SKILLS_DIRECTORY)
    return target_directory


def _list_subagent_skills(
    skills_root: Path,
    subagent_name: str | None,
    subagent_names: set[str],
) -> dict[str, list[dict[str, str]]]:
    """读取子 Agent 技能的标题和描述，不返回技能正文。"""
    names = [subagent_name] if subagent_name else sorted(subagent_names)
    if subagent_name is not None:
        _validate_target_name(subagent_name, subagent_names)

    result: dict[str, list[dict[str, str]]] = {}
    for name in names:
        directory = (
            skills_root / MAIN_SKILLS_DIRECTORY
            if name == MAIN_SKILLS_DIRECTORY
            else skills_root / SUBAGENTS_DIRECTORY / name
        )
        skills: list[dict[str, str]] = []
        for skill_directory in sorted(directory.iterdir(), key=lambda path: path.name):
            if not skill_directory.is_dir():
                continue
            try:
                metadata = _parse_skill_metadata(skill_directory)
            except (OSError, ValueError):
                continue
            skills.append({"skill_name": skill_directory.name, **metadata})
        result[name] = skills
    return result


def _delete_subagent_skill(
    skills_root: Path,
    skill_name: str,
    subagent_name: str,
    subagent_names: set[str],
) -> None:
    """删除目标子 Agent 的一个技能目录。"""
    _validate_subagent_name(subagent_name, subagent_names)
    skill_directory = _skill_directory(
        skills_root / SUBAGENTS_DIRECTORY / subagent_name,
        skill_name,
    )
    if not skill_directory.is_dir():
        raise ValueError(f"子 Agent '{subagent_name}' 不存在技能 '{skill_name}'")
    shutil.rmtree(skill_directory)


def _update_subagent_skill(
    skills_root: Path,
    skill_url: str,
    subagent_name: str,
    subagent_names: set[str],
) -> dict[str, Any]:
    """下载新版本并原子替换子 Agent 已分配的同名技能。"""
    _validate_subagent_name(subagent_name, subagent_names)
    skill_name, _, _ = _resolve_skill_source(skill_url)
    target_directory = _skill_directory(
        skills_root / SUBAGENTS_DIRECTORY / subagent_name,
        skill_name,
    )
    if not target_directory.is_dir():
        raise ValueError(f"子 Agent '{subagent_name}' 不存在技能 '{skill_name}'")

    staging_directory = _skill_directory(skills_root / MAIN_SKILLS_DIRECTORY, skill_name)
    if staging_directory.exists():
        raise ValueError(f"主 Agent 已存在暂存技能 '{skill_name}'，请先分配或删除后再更新")

    backup_directory = target_directory.with_name(f".{skill_name}.backup")
    if backup_directory.exists():
        raise ValueError(f"技能 '{skill_name}' 存在未清理的更新备份")

    shutil.move(str(target_directory), backup_directory)
    try:
        metadata = _download_skill(skills_root, skill_url)
        _assign_skill(skills_root, skill_name, subagent_name, subagent_names)
    except Exception:
        # 已下载但尚未成功分配的新版本不能遗留在主 Agent 的目录中。
        if staging_directory.exists():
            shutil.rmtree(staging_directory)
        if target_directory.exists():
            shutil.rmtree(target_directory)
        shutil.move(str(backup_directory), target_directory)
        raise
    else:
        shutil.rmtree(backup_directory)
    return {**metadata, "subagent_name": subagent_name}


def _cleanup_packages(directory: Path) -> None:
    """清理目录中遗留的技能压缩包。"""
    for path in directory.iterdir():
        if path.is_file() and path.name.lower().endswith(PACKAGE_SUFFIXES):
            path.unlink()
