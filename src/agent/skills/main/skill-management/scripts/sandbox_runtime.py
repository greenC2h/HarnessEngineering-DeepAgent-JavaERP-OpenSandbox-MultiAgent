"""可信沙箱事务入口；只运行管理代码，技能内容始终作为数据处理。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys

import skill_management as management


ROOT = Path("/skills")
MAX_BYTES = 32 * 1024 * 1024
MAX_FILES = 2048


def safe_path(path: Path) -> Path:
    """
    拒绝路径任意层级的链接，防止复制或回滚越界。
    """
    path.relative_to(ROOT)
    if ".." in path.parts:
        raise ValueError("技能路径不能包含上级目录")
    for item in [path, *path.parents]:
        if item.is_symlink():
            raise ValueError("技能路径不能包含符号链接")
        if item == ROOT:
            break
    return path


def manifest(directory: Path) -> list[dict]:
    """
    限制导出大小并记录摘要，控制面下载后重新核验。
    """
    safe_path(directory)
    result = []
    size = 0
    entries = 0
    for parent, directories, files in os.walk(directory, followlinks=False):
        entries += len(directories) + len(files)
        if entries > MAX_FILES:
            raise ValueError("技能目录项超过限制")
        for name in directories + files:
            path = safe_path(Path(parent) / name)
            mode = path.lstat().st_mode
            if not stat.S_ISDIR(mode) and not stat.S_ISREG(mode):
                raise ValueError("技能只能包含普通文件和目录")
        for name in files:
            path = Path(parent) / name
            size += path.stat().st_size
            if size > MAX_BYTES or len(result) >= MAX_FILES:
                raise ValueError("技能导出超过文件数或大小限制")
            result.append({"path": path.relative_to(directory).as_posix(),
                           "size": path.stat().st_size,
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    return result


def restore(transaction: Path, state: dict) -> None:
    """
    按持久事务记录恢复原目录；恢复失败时保留备份供重试。
    """
    for index, relative in enumerate(state["paths"]):
        destination = safe_path(ROOT / relative)
        if destination.exists():
            manifest(destination)
            shutil.rmtree(destination)
        backup = transaction / str(index)
        if backup.exists():
            shutil.copytree(backup, destination)
    shutil.rmtree(transaction)


def dispatch(request: dict) -> dict:
    """
    执行一次下载、查询或可回滚变更；调用者负责最终提交。
    """
    operation = request["operation"]
    if "token" in request:
        token = request["token"]
        if len(token) != 32 or any(char not in "0123456789abcdef" for char in token):
            raise ValueError("无效事务标识")
    names = set(request["names"])
    for name in names:
        management._skill_directory(ROOT, name)
        safe_path(ROOT / "subagents" / name)
    safe_path(ROOT / "main")
    management._ensure_skill_directories(ROOT, names)
    if operation in {"rollback", "finish", "release"}:
        token = request["token"]
        transaction = safe_path(ROOT / ".skill-transactions" / token)
        if operation == "rollback" and not transaction.exists():
            return {"ok": True}
        state = json.loads((transaction / "state.json").read_text())
        if operation == "rollback":
            restore(transaction, state)
        elif operation == "release":
            shutil.rmtree(transaction)
        # finish 只确认事务仍可提交；收到确认前保留备份，以便响应丢失时回滚。
        return {"ok": True}
    target = request.get("target")
    if operation == "list":
        selected = [target] if target else sorted(names)
        for name in selected:
            management._validate_target_name(name, names)
            directory = ROOT / "main" if name == "main" else ROOT / "subagents" / name
            for child in directory.iterdir():
                safe_path(child)
                if child.is_dir():
                    manifest(child)
        return management._list_subagent_skills(ROOT, target, names)
    skill = request.get("skill")
    if operation in {"download", "update"}:
        skill, _, _ = management._resolve_skill_source(request["url"])
    source = safe_path(management._skill_directory(ROOT / "main", skill))
    if operation == "download":
        return management._download_skill(ROOT, request["url"])
    management._validate_target_name(target, names)
    destination = source if target == "main" else safe_path(
        management._skill_directory(ROOT / "subagents" / target, skill))
    paths = list(dict.fromkeys([source, destination] if operation != "delete" else [destination]))
    for path in paths:
        if path.exists():
            manifest(path)
    transaction = safe_path(ROOT / ".skill-transactions" / request["token"])
    transaction.mkdir(parents=True, exist_ok=False)
    state = {"paths": [path.relative_to(ROOT).as_posix() for path in paths]}
    for index, path in enumerate(paths):
        if path.exists():
            shutil.copytree(path, transaction / str(index))
    (transaction / "state.json").write_text(json.dumps(state))
    try:
        if operation == "assign":
            management._ensure_skill_metadata(source)
            management._assign_skill(ROOT, skill, target, names)
        elif operation == "update":
            management._update_subagent_skill(ROOT, request["url"], target, names)
        elif operation == "delete":
            management._delete_subagent_skill(ROOT, skill, target, names)
        else:
            raise ValueError("未知技能操作")
        files = manifest(destination) if operation != "delete" else []
        return {"skill": skill, "directory": destination.relative_to(ROOT).as_posix(), "files": files}
    except Exception:
        restore(transaction, state)
        raise


if __name__ == "__main__":
    try:
        print(json.dumps({"result": dispatch(json.loads(sys.argv[1]))}, ensure_ascii=False))
    except Exception as error:
        # 原始错误可能含内部路径；控制面只展示稳定的错误类别。
        print(json.dumps({"error": type(error).__name__}))
        sys.exit(1)
