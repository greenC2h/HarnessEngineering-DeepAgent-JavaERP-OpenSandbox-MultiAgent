"""部署时 Vite 默认资源 URL 与静态兼容路径的路由回归测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.chat import _mount_web_assets, index


class WebAssetRouteTests(unittest.TestCase):
    """用隔离的构建目录检查真实首页和静态路由，不运行应用 lifespan。"""

    def test_built_homepage_script_and_stylesheet_urls_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            web_dir = root / "dist"
            assets_dir = web_dir / "assets"
            assets_dir.mkdir(parents=True)
            (web_dir / "index.html").write_text(
                '<script src="/assets/index-test.js"></script><link rel="stylesheet" href="/assets/index-test.css">',
                encoding="utf-8",
            )
            (assets_dir / "index-test.js").write_text("console.log('ready');", encoding="utf-8")
            (assets_dir / "index-test.css").write_text("body { color: black; }", encoding="utf-8")
            (root / "private.txt").write_text("private", encoding="utf-8")
            application = FastAPI()
            _mount_web_assets(application, web_dir)
            application.add_api_route("/", index)
            with patch("api.chat.WEB_DIR", web_dir), TestClient(application) as client:
                homepage = client.get("/")
                self.assertEqual(homepage.status_code, 200)
                self.assertIn("/assets/index-test.js", homepage.text)
                self.assertEqual(client.get("/assets/index-test.js").status_code, 200)
                self.assertEqual(client.get("/assets/index-test.css").status_code, 200)
                self.assertEqual(client.get("/static/assets/index-test.js").status_code, 200)
                self.assertEqual(client.get("/assets/missing.js").status_code, 404)
                self.assertEqual(client.get("/assets/%2e%2e/%2e%2e/private.txt").status_code, 404)

    def test_legacy_static_directory_does_not_require_assets_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            web_dir = Path(temporary)
            (web_dir / "index.html").write_text("legacy", encoding="utf-8")
            application = FastAPI()
            _mount_web_assets(application, web_dir)
            with TestClient(application) as client:
                self.assertEqual(client.get("/static/index.html").status_code, 200)
                self.assertEqual(client.get("/assets/missing.js").status_code, 404)
