"""持久化图表资源，并提供给前端访问的稳定资源路径。"""

from __future__ import annotations

import asyncio
import logging
import mimetypes
import os
import re
import time
from pathlib import Path
from uuid import uuid4


PROJECT_DIR = Path(__file__).resolve().parents[2]
VISUALIZATION_DIR = PROJECT_DIR / "runtime" / "visualizations"
ARTIFACT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
DEFAULT_TTL_DAYS = 7
DEFAULT_CLEANUP_INTERVAL_SECONDS = 3600
# 新图表写入 HTML；图片后缀只用于恢复切换前已保存的历史图表和过期占位资源。
_ARTIFACT_SUFFIXES = {".html", ".htm", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bin"}
EXPIRED_VISUALIZATION_SVG = """<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
<rect width="640" height="360" fill="#f4f6f8"/>
<rect x="1" y="1" width="638" height="358" fill="none" stroke="#c9d0d8"/>
<path d="M230 235h180M255 235v-70h45v70m20 0v-105h45v105m20 0v-45h45v45" fill="none" stroke="#8995a3" stroke-width="10"/>
<text x="320" y="285" text-anchor="middle" fill="#536171" font-family="Arial, sans-serif" font-size="24">图表已过期</text>
</svg>"""
logger = logging.getLogger(__name__)


def _positive_env_float(name: str, default: float) -> float:
    """读取正数运行参数，非法配置时回退到默认值。"""
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def visualization_ttl_seconds() -> float:
    """返回图表资源有效期，默认由七天换算而来。"""
    return _positive_env_float("MYAGENT_VISUALIZATION_TTL_DAYS", DEFAULT_TTL_DAYS) * 86400


def visualization_cleanup_interval_seconds() -> float:
    """返回后台清理周期，默认每小时执行一次。"""
    return _positive_env_float(
        "MYAGENT_VISUALIZATION_CLEANUP_INTERVAL_SECONDS",
        DEFAULT_CLEANUP_INTERVAL_SECONDS,
    )


def _extension_for_mime_type(mime_type: str) -> str:
    """把图表资源 MIME 类型转换为稳定的文件扩展名。"""
    normalized = mime_type.lower().split(";", 1)[0]
    if normalized == "text/html":
        return ".html"
    return ".png" if normalized == "image/png" else mimetypes.guess_extension(normalized) or ".bin"


def save_visualization(data: bytes, mime_type: str) -> dict[str, str]:
    """
    将图表 HTML 或历史兼容图片保存到运行时资源目录，并返回稳定的资源标识。

    资源不写入 LangGraph 消息正文；消息只保存返回的 artifact_id，避免 checkpoint
    膨胀，也避免要求当前文本模型处理完整图表内容。
    """
    if not data:
        raise ValueError("图表资源为空")
    normalized_mime = mime_type.lower().split(";", 1)[0] or "image/png"
    artifact_id = uuid4().hex
    extension = _extension_for_mime_type(normalized_mime)
    VISUALIZATION_DIR.mkdir(parents=True, exist_ok=True)
    path = VISUALIZATION_DIR / f"{artifact_id}{extension}"
    path.write_bytes(data)
    return {
        "artifact_id": artifact_id,
        "mime_type": normalized_mime,
        "path": str(path),
    }


def get_visualization_path(artifact_id: str) -> Path | None:
    """按资源标识定位未过期的图表文件，并拒绝路径穿越输入。"""
    if not ARTIFACT_ID_PATTERN.fullmatch(artifact_id):
        return None
    matches = list(VISUALIZATION_DIR.glob(f"{artifact_id}.*"))
    if len(matches) != 1 or not matches[0].is_file() or matches[0].is_symlink():
        return None
    try:
        if matches[0].stat().st_mtime <= time.time() - visualization_ttl_seconds():
            return None
    except OSError:
        return None
    return matches[0]


def cleanup_expired_visualizations(now: float | None = None) -> int:
    """删除超过有效期的图表文件，并返回删除数量。"""
    if not VISUALIZATION_DIR.is_dir():
        return 0
    cutoff = (time.time() if now is None else now) - visualization_ttl_seconds()
    deleted_count = 0
    for path in VISUALIZATION_DIR.iterdir():
        if path.suffix.lower() not in _ARTIFACT_SUFFIXES or path.is_symlink() or not path.is_file():
            continue
        try:
            if path.stat().st_mtime <= cutoff:
                path.unlink()
                deleted_count += 1
        except FileNotFoundError:
            continue
        except OSError:
            logger.warning("无法清理过期图表资源: %s", path.name)
    return deleted_count


async def run_visualization_cleanup(stop_event: asyncio.Event) -> None:
    """在 FastAPI 生命周期内定时清理过期图表资源。"""
    while not stop_event.is_set():
        deleted_count = await asyncio.to_thread(cleanup_expired_visualizations)
        if deleted_count:
            logger.info("已清理过期图表资源: %s 个", deleted_count)
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=visualization_cleanup_interval_seconds(),
            )
        except asyncio.TimeoutError:
            continue


def visualization_src(artifact_id: str) -> str:
    """返回前端和历史消息共同使用的相对资源路径。"""
    return f"/visualizations/{artifact_id}"
