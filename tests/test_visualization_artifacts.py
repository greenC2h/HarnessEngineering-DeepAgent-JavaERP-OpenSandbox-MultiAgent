"""图表资源保存、过期和占位图片测试。"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from services import visualization_artifacts
from api.chat import download_analysis_report, visualization


class VisualizationArtifactTests(unittest.IsolatedAsyncioTestCase):
    """验证图表文件过期后不会继续返回旧资源。"""

    def test_resolves_the_project_runtime_directory_after_module_move(self) -> None:
        """资源目录必须仍位于 MotoParts Agent ERP/runtime，而不是 services 的父目录。"""
        self.assertEqual(
            visualization_artifacts.PROJECT_DIR,
            Path(__file__).resolve().parents[1],
        )

    def test_expired_file_is_removed_and_no_longer_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            visualization_artifacts,
            "VISUALIZATION_DIR",
            Path(temp_dir),
        ), patch.dict("os.environ", {"MYAGENT_VISUALIZATION_TTL_DAYS": "1"}):
            artifact = visualization_artifacts.save_visualization(b"png", "image/png")
            path = Path(artifact["path"])
            old_time = path.stat().st_mtime - 2 * 86400
            os.utime(path, (old_time, old_time))

            self.assertIsNone(
                visualization_artifacts.get_visualization_path(artifact["artifact_id"])
            )
            self.assertEqual(visualization_artifacts.cleanup_expired_visualizations(), 1)
            self.assertFalse(path.exists())

    def test_html_artifact_uses_html_extension(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            visualization_artifacts,
            "VISUALIZATION_DIR",
            Path(temp_dir),
        ):
            artifact = visualization_artifacts.save_visualization(
                b"<html><body>chart</body></html>",
                "text/html",
            )

            path = Path(artifact["path"])
            self.assertEqual(path.suffix, ".html")
            self.assertEqual(path.read_bytes(), b"<html><body>chart</body></html>")

    async def test_missing_visualization_returns_expired_placeholder(self) -> None:
        response = await visualization("d" * 32)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.media_type, "image/svg+xml")
        self.assertIn("图表已过期", response.body.decode("utf-8"))

    async def test_html_visualization_uses_sandboxed_inline_response(self) -> None:
        """打开图表时必须保留 HTML MIME 类型和脚本隔离响应头。"""
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            visualization_artifacts,
            "VISUALIZATION_DIR",
            Path(temp_dir),
        ):
            artifact = visualization_artifacts.save_visualization(
                b"<html><body>chart</body></html>",
                "text/html",
            )

            response = await visualization(artifact["artifact_id"])

        self.assertEqual(response.media_type, "text/html")
        self.assertEqual(response.headers["content-security-policy"], "sandbox allow-scripts")
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertNotIn("content-disposition", response.headers)

    async def test_html_visualization_downloads_as_an_attachment(self) -> None:
        """下载入口只能为暂存的 HTML 图表设置附件响应头。"""
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(
            visualization_artifacts,
            "VISUALIZATION_DIR",
            Path(temp_dir),
        ):
            artifact = visualization_artifacts.save_visualization(
                b"<html><body>chart</body></html>",
                "text/html",
            )

            response = await visualization(artifact["artifact_id"], download=True)

        self.assertEqual(response.media_type, "text/html")
        self.assertEqual(
            response.headers["content-disposition"],
            f'attachment; filename="chart-{artifact["artifact_id"]}.html"',
        )

    async def test_report_download_reads_sandbox_content_without_local_artifact(self) -> None:
        """报告下载只透传沙箱字节，不走本地图表 artifact 存储。"""
        with patch(
            "api.chat.agent_loader.download_sandbox_report",
            new=AsyncMock(return_value=("report_20260928_120000.md", b"# report")),
        ) as download:
            response = await download_analysis_report("e" * 32, user_id="u1")

        download.assert_awaited_once_with("u1", "e" * 32)
        self.assertEqual(response.body, b"# report")
        self.assertTrue(response.media_type.startswith("text/markdown"))
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="report_20260928_120000.md"',
        )


if __name__ == "__main__":
    unittest.main()
