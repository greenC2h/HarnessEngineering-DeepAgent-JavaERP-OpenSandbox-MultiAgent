"""MySQL 认证接口的输入、凭据与会话回归测试。"""

from __future__ import annotations

import hashlib
import unittest

from fastapi import HTTPException, Response
from pydantic import ValidationError
from starlette.requests import Request

from agent.schema import AuthRequest, RegisterRequest
from api import auth


class FakeAuthRepository:
    """隔离认证单元测试的内存仓储，接口与生产 MySQL 仓储保持一致。"""

    def __init__(self) -> None:
        self.users: dict[str, dict[str, str]] = {}
        self.sessions: dict[str, str] = {}
        self.initialized = False

    def ensure_initialized(self) -> None:
        self.initialized = True

    def create_user(self, account: str, password_hash: str) -> dict[str, str] | None:
        if account in self.users:
            return None
        user_id = f"u-{account}"
        self.users[account] = {"user_id": user_id, "account": account, "password_hash": password_hash}
        return {"user_id": user_id, "username": account}

    def find_user_by_account(self, account: str) -> dict[str, str] | None:
        return self.users.get(account)

    def create_session(self, user_id: str) -> str:
        token = f"token-{user_id}"
        self.sessions[hashlib.sha256(token.encode("utf-8")).hexdigest()] = user_id
        return token

    def find_session_user(self, token: str) -> dict[str, str] | None:
        user_id = self.sessions.get(hashlib.sha256(token.encode("utf-8")).hexdigest())
        if user_id is None:
            return None
        account = next(account for account, user in self.users.items() if user["user_id"] == user_id)
        return {"user_id": user_id, "username": account}

    def delete_session(self, token: str) -> None:
        self.sessions.pop(hashlib.sha256(token.encode("utf-8")).hexdigest(), None)


def make_request_with_cookie(token: str | None = None) -> Request:
    """创建只包含认证 Cookie 的最小 ASGI 请求。"""
    headers = [] if token is None else [(b"cookie", f"{auth.SESSION_COOKIE_NAME}={token}".encode("ascii"))]
    return Request({"type": "http", "method": "GET", "path": "/auth/me", "headers": headers})


class AuthTests(unittest.IsolatedAsyncioTestCase):
    """验证账号密码规则、注册验证码和持久会话的接口契约。"""

    async def asyncSetUp(self) -> None:
        self.original_repository = auth._repository
        self.repository = FakeAuthRepository()
        auth._repository = self.repository
        auth._captchas.clear()

    async def asyncTearDown(self) -> None:
        auth._repository = self.original_repository
        auth._captchas.clear()

    async def test_register_requires_captcha_and_login_does_not(self) -> None:
        """注册消费验证码，登录只验证账号密码并创建 HttpOnly 会话。"""
        captcha = await auth.get_captcha()
        answer = auth._captchas[captcha.captcha_id].answer
        response = Response()
        created = await auth.register(
            RegisterRequest(account="123456", password="secure-pass", captcha_id=captcha.captcha_id, captcha=answer),
            response,
        )
        self.assertEqual(created.username, "123456")
        self.assertTrue(self.repository.initialized)
        self.assertIn("httponly", response.headers["set-cookie"].lower())

        login_response = Response()
        logged_in = await auth.login(AuthRequest(account="123456", password="secure-pass"), login_response)
        self.assertEqual(logged_in.user_id, created.user_id)
        self.assertIn("myagent_session=", login_response.headers["set-cookie"])

    async def test_invalid_credentials_and_session_are_rejected(self) -> None:
        """未知账号、错误密码和失效会话均返回明确的登录失败信息。"""
        with self.assertRaisesRegex(HTTPException, "账号或密码错误") as unknown:
            await auth.login(AuthRequest(account="123456", password="secure-pass"), Response())
        self.assertEqual(unknown.exception.status_code, 401)

        with self.assertRaisesRegex(HTTPException, "登录已失效") as expired:
            await auth.get_current_user(make_request_with_cookie("invalid"))
        self.assertEqual(expired.exception.status_code, 401)

    async def test_current_user_and_logout_follow_cookie_session(self) -> None:
        """登录态检查和退出必须读取并删除同一个持久化会话。"""
        captcha = await auth.get_captcha()
        created = await auth.register(
            RegisterRequest(
                account="123456",
                password="secure-pass",
                captcha_id=captcha.captcha_id,
                captcha=auth._captchas[captcha.captcha_id].answer,
            ),
            Response(),
        )
        token = self.repository.create_session(created.user_id)
        current = await auth.get_current_user(make_request_with_cookie(token))
        self.assertEqual(current, created)

        response = Response()
        await auth.logout(make_request_with_cookie(token), response)
        self.assertIn("Max-Age=0", response.headers["set-cookie"])
        with self.assertRaises(HTTPException):
            await auth.get_current_user(make_request_with_cookie(token))

    def test_account_and_password_rules_are_enforced(self) -> None:
        """账号仅允许 6-20 位数字，密码长度限制在 8-64 位。"""
        for account, password in (("12345", "secure-pass"), ("123456", "short"), ("123456a", "secure-pass")):
            with self.assertRaises(ValidationError):
                AuthRequest(account=account, password=password)
