"""验证 ERP 失败不会伪装为成功数据，也不会自动重试写操作。"""

from __future__ import annotations

import unittest

import httpx
from fastmcp.exceptions import ToolError

from mcp_server.http_base import request_erp


class ErpResponseTests(unittest.IsolatedAsyncioTestCase):
    """使用隔离 HTTP transport 覆盖业务、协议和网络失败。"""

    async def test_empty_success_is_distinct_from_business_failure(self) -> None:
        """
        成功的空列表与业务错误必须分别返回数据和抛出工具异常。
        """
        for code in (200, 400):
            with self.subTest(code=code):
                transport = httpx.MockTransport(
                    lambda request: httpx.Response(200, json={"code": code, "data": []})
                )
                async with httpx.AsyncClient(transport=transport, base_url="http://erp.test") as client:
                    if code == 200:
                        self.assertEqual(await request_erp(client, "GET", "/inventory/warning"), [])
                    else:
                        with self.assertRaises(ToolError):
                            await request_erp(client, "GET", "/inventory/warning")

    async def test_invalid_response_does_not_leak_body(self) -> None:
        """
        HTTP 错误和无效 JSON 不应把原始响应中的敏感内容回传给模型。
        """
        for status in (200, 503):
            with self.subTest(status=status):
                transport = httpx.MockTransport(
                    lambda request: httpx.Response(status, text="private-debug-secret")
                )
                async with httpx.AsyncClient(transport=transport, base_url="http://erp.test") as client:
                    with self.assertRaises(ToolError) as caught:
                        await request_erp(client, "GET", "/inventory/warning")
                    self.assertNotIn("private-debug-secret", str(caught.exception))

    async def test_business_error_includes_safe_code_and_message(self) -> None:
        """可公开的业务码和短消息应保留给调用方排障。"""
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"code": 422, "message": "订单状态不允许修改"})
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://erp.test") as client:
            with self.assertRaisesRegex(ToolError, "业务码 422.*订单状态不允许修改"):
                await request_erp(client, "PUT", "/orders/update/128", json={})

    async def test_business_error_does_not_expose_sensitive_message(self) -> None:
        """业务响应的敏感调试文本仍应退化为通用提示。"""
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, json={"code": 500, "message": "token=private-debug-secret"})
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://erp.test") as client:
            with self.assertRaises(ToolError) as caught:
                await request_erp(client, "PUT", "/orders/update/128", json={})
        self.assertIn("业务码 500", str(caught.exception))
        self.assertNotIn("private-debug-secret", str(caught.exception))

    async def test_write_timeout_is_not_retried(self) -> None:
        """
        超时可能发生在服务端已经写入后，因此调用方只能得到结果未确认的错误。
        """
        requests = []

        def respond(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            raise httpx.ReadTimeout("private-debug-secret", request=request)

        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), base_url="http://erp.test"
        ) as client:
            with self.assertRaisesRegex(ToolError, "结果尚未确认"):
                await request_erp(client, "POST", "/orders/create", json={"orderDetail": []})
        self.assertEqual(len(requests), 1)
