"""管理 Java ERP HTTP 客户端的 MCP 生命周期资源。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import re
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from mcp_server.server_config import JAVA_API_BASE_URL


_SAFE_ERP_MESSAGE = re.compile(r"^(?!.*(?:password|token|authorization|secret)).{1,240}$", re.IGNORECASE | re.DOTALL)


def _business_error(result: dict[str, Any]) -> str:
    """将 ERP 业务失败压缩为可诊断且不含响应体的工具错误。"""
    code = result.get("code")
    message = result.get("message") or result.get("msg")
    suffix = f"（业务码 {code}）" if isinstance(code, (int, str)) else ""
    if isinstance(message, str):
        normalized = " ".join(message.split())
        if _SAFE_ERP_MESSAGE.fullmatch(normalized):
            return f"ERP 未确认本次业务操作成功{suffix}：{normalized}"
    return f"ERP 未确认本次业务操作成功{suffix}，请检查请求参数或服务日志。"


async def request_erp(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    **kwargs: Any,
) -> Any:
    """
    解包 ERP 业务响应；失败通过 MCP 错误通道返回，不伪装成查询数据。

    不自动重试写请求，避免超时后重复创建订单；错误不暴露认证信息或响应正文。
    """
    try:
        response = await client.request(method, path, **kwargs)
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise ToolError("ERP 请求超时，结果尚未确认；写操作请先查询状态再决定是否重试。") from exc
    except httpx.HTTPStatusError as exc:
        raise ToolError(f"ERP 服务返回 HTTP {exc.response.status_code}，本次操作未确认成功。") from exc
    except httpx.RequestError as exc:
        raise ToolError("无法连接 ERP 服务，请稍后重试。") from exc
    try:
        result = response.json()
    except ValueError as exc:
        raise ToolError("ERP 返回了无法解析的响应。") from exc
    if not isinstance(result, dict) or result.get("code") != 200:
        raise ToolError(_business_error(result) if isinstance(result, dict) else "ERP 未确认本次业务操作成功，请检查请求参数或服务日志。")
    return result.get("data")


@asynccontextmanager
async def mcp_lifespan(_: FastMCP) -> AsyncIterator[dict[str, httpx.AsyncClient]]:
    """
    为全部 MCP 工具提供共享的异步 Java API 客户端，并在关闭时释放连接。
    """
    timeout = httpx.Timeout(15.0)
    async with httpx.AsyncClient(
        base_url=JAVA_API_BASE_URL,
        timeout=timeout,
    ) as http_client:
        yield {"http_client": http_client}
