"""基于 MySQL 的账号密码认证与注册验证码接口。"""

from __future__ import annotations

import base64
import asyncio
import hashlib
import html
import os
import secrets
import re
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pymysql
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Request, Response

from agent.schema import AuthRequest, AuthResponse, CaptchaResponse, RegisterRequest


CAPTCHA_TTL_SECONDS = 300
CAPTCHA_LENGTH = 4
SESSION_COOKIE_NAME = "myagent_session"
SESSION_TTL_DAYS = 7
PBKDF2_ITERATIONS = 600_000
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 启动器与直接 uvicorn 启动都应读取同一份本地配置；环境变量始终优先于 .env。
load_dotenv(PROJECT_ROOT / ".env")
MYSQL_HOST = os.getenv("MYAGENT_AUTH_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYAGENT_AUTH_MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv("MYAGENT_AUTH_MYSQL_DATABASE", "myagent_auth")
MYSQL_USER = os.getenv("MYAGENT_AUTH_MYSQL_USER", "root")
MYSQL_PASSWORD = os.getenv("MYAGENT_AUTH_MYSQL_PASSWORD", "")

if not re.fullmatch(r"[A-Za-z0-9_]+", MYSQL_DATABASE):
    raise RuntimeError("MYAGENT_AUTH_MYSQL_DATABASE 只能包含字母、数字和下划线")


@dataclass
class _Captcha:
    answer: str
    expires_at: float


_captchas: dict[str, _Captcha] = {}
router = APIRouter(prefix="/auth", tags=["auth"])


class AuthRepository:
    """封装认证用户与持久化会话的 MySQL 访问。"""

    def __init__(self) -> None:
        self._initialized = False
        self._initialization_lock = threading.Lock()

    def _connect(self, *, database: bool = True):
        """建立短生命周期连接，避免在异步请求间共享 MySQL 游标。"""
        options: dict[str, Any] = {
            "host": MYSQL_HOST,
            "port": MYSQL_PORT,
            "user": MYSQL_USER,
            "password": MYSQL_PASSWORD,
            "charset": "utf8mb4",
            "autocommit": True,
            "cursorclass": pymysql.cursors.DictCursor,
        }
        if database:
            options["database"] = MYSQL_DATABASE
        return pymysql.connect(**options)

    def ensure_initialized(self) -> None:
        """创建认证库和表；此方法可重复调用且不覆盖已有用户。"""
        if self._initialized:
            return
        with self._initialization_lock:
            if self._initialized:
                return
            with self._connect(database=False) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DATABASE}` "
                        "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                    )
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS auth_users (
                            user_id CHAR(38) PRIMARY KEY,
                            account VARCHAR(20) NOT NULL UNIQUE,
                            password_hash VARCHAR(255) NOT NULL,
                            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                        """
                    )
                    cursor.execute(
                        """
                        CREATE TABLE IF NOT EXISTS auth_sessions (
                            session_hash CHAR(64) PRIMARY KEY,
                            user_id CHAR(38) NOT NULL,
                            expires_at DATETIME NOT NULL,
                            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                            INDEX idx_auth_sessions_expires_at (expires_at),
                            CONSTRAINT fk_auth_sessions_user
                                FOREIGN KEY (user_id) REFERENCES auth_users(user_id)
                                ON DELETE CASCADE
                        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                        """
                    )
            self._initialized = True

    def create_user(self, account: str, password_hash: str) -> dict[str, str] | None:
        """创建账号；账号已存在时返回 ``None``。"""
        user_id = f"u-{uuid.uuid4().hex}"
        try:
            with self._connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "INSERT INTO auth_users (user_id, account, password_hash) VALUES (%s, %s, %s)",
                        (user_id, account, password_hash),
                    )
        except pymysql.err.IntegrityError:
            return None
        return {"user_id": user_id, "username": account}

    def find_user_by_account(self, account: str) -> dict[str, str] | None:
        """返回验证密码所需的用户记录，不存在时返回 ``None``。"""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT user_id, account, password_hash FROM auth_users WHERE account = %s",
                    (account,),
                )
                return cursor.fetchone()

    def create_session(self, user_id: str) -> str:
        """创建一周有效的随机会话，并只持久化其 SHA-256 摘要。"""
        token = secrets.token_urlsafe(32)
        session_hash = _hash_session_token(token)
        expires_at = datetime.now(UTC) + timedelta(days=SESSION_TTL_DAYS)
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM auth_sessions WHERE expires_at <= UTC_TIMESTAMP()")
                cursor.execute(
                    "INSERT INTO auth_sessions (session_hash, user_id, expires_at) VALUES (%s, %s, %s)",
                    (session_hash, user_id, expires_at.replace(tzinfo=None)),
                )
        return token

    def find_session_user(self, token: str) -> dict[str, str] | None:
        """验证会话令牌并返回当前登录用户。"""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT u.user_id, u.account
                    FROM auth_sessions AS s
                    INNER JOIN auth_users AS u ON u.user_id = s.user_id
                    WHERE s.session_hash = %s AND s.expires_at > UTC_TIMESTAMP()
                    """,
                    (_hash_session_token(token),),
                )
                record = cursor.fetchone()
        if record is None:
            return None
        return {"user_id": record["user_id"], "username": record["account"]}

    def delete_session(self, token: str) -> None:
        """删除退出登录时提供的会话，未知令牌无需报错。"""
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("DELETE FROM auth_sessions WHERE session_hash = %s", (_hash_session_token(token),))


_repository = AuthRepository()


def _hash_session_token(token: str) -> str:
    """生成固定长度会话摘要，数据库中不保存可直接使用的 Cookie 值。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _hash_password(password: str) -> str:
    """使用独立随机盐生成 PBKDF2 密码哈希。"""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    """使用常量时间比较校验已保存的 PBKDF2 密码哈希。"""
    try:
        algorithm, iteration_text, salt_text, digest_text = encoded.split("$", maxsplit=3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_text), int(iteration_text),
        )
        return secrets.compare_digest(digest.hex(), digest_text)
    except (TypeError, ValueError):
        return False


async def _repository_call(method, *args):
    """将同步 MySQL 调用隔离到工作线程，避免阻塞 FastAPI 事件循环。"""
    return await asyncio.to_thread(method, *args)


async def _ensure_repository() -> None:
    """确保认证数据库已初始化，并将连接故障转换为可理解的服务错误。"""
    try:
        await _repository_call(_repository.ensure_initialized)
    except pymysql.MySQLError as error:
        raise HTTPException(status_code=503, detail="认证数据库暂时不可用，请稍后重试") from error


def _captcha_svg(answer: str) -> str:
    """生成带干扰图形和旋转数字的验证码 SVG。"""
    lines = "".join(
        f'<path d="M{secrets.randbelow(180)} {secrets.randbelow(56)} '
        f'L{secrets.randbelow(180)} {secrets.randbelow(56)}" />'
        for _ in range(8)
    )
    noise = "".join(
        f'<circle cx="{secrets.randbelow(180)}" cy="{secrets.randbelow(56)}" '
        f'r="{1 + secrets.randbelow(3)}" />'
        for _ in range(32)
    )
    digits = "".join(
        f'<text x="{22 + index * 38}" y="38" transform="rotate({secrets.randbelow(25) - 12} '
        f' {38 + index * 38} 28)">{html.escape(digit)}</text>'
        for index, digit in enumerate(answer)
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="180" height="56" viewBox="0 0 180 56">'
        '<rect width="180" height="56" rx="8" fill="#e8edf2"/>'
        '<g fill="none" stroke="#8aa0b5" stroke-width="1.2" opacity=".75">'
        f'{lines}</g><g fill="#59738b" opacity=".5">{noise}</g>'
        '<g font-family="Arial,sans-serif" font-size="29" font-weight="700" fill="#16324a">'
        f"{digits}</g></svg>"
    )


def _new_captcha() -> CaptchaResponse:
    """创建验证码并只返回图片，不暴露答案。"""
    _purge_captchas()
    captcha_id = uuid.uuid4().hex
    answer = "".join(str(secrets.randbelow(10)) for _ in range(CAPTCHA_LENGTH))
    _captchas[captcha_id] = _Captcha(answer=answer, expires_at=time.monotonic() + CAPTCHA_TTL_SECONDS)
    image = base64.b64encode(_captcha_svg(answer).encode("utf-8")).decode("ascii")
    return CaptchaResponse(captcha_id=captcha_id, image=f"data:image/svg+xml;base64,{image}")


def _purge_captchas() -> None:
    now = time.monotonic()
    for captcha_id, captcha in list(_captchas.items()):
        if captcha.expires_at <= now:
            _captchas.pop(captcha_id, None)


def _verify_captcha(request: AuthRequest) -> None:
    captcha = _captchas.pop(request.captcha_id, None)
    if captcha is None or captcha.expires_at <= time.monotonic() or not secrets.compare_digest(
        captcha.answer, request.captcha.strip()
    ):
        raise HTTPException(status_code=400, detail="验证码错误或已过期，请刷新后重试")


@router.get("/captcha", response_model=CaptchaResponse)
async def get_captcha() -> CaptchaResponse:
    return _new_captcha()


def _set_session_cookie(response: Response, token: str) -> None:
    """写入 HttpOnly 登录 Cookie，浏览器 JavaScript 不可读取其内容。"""
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL_DAYS * 24 * 60 * 60,
        httponly=True,
        samesite="lax",
        secure=False,
        path="/",
    )


@router.post("/register", response_model=AuthResponse)
async def register(request: RegisterRequest, response: Response) -> AuthResponse:
    """验证注册验证码，创建 MySQL 用户并建立登录会话。"""
    _verify_captcha(request)
    await _ensure_repository()
    created = await _repository_call(_repository.create_user, request.account, _hash_password(request.password))
    if created is None:
        raise HTTPException(status_code=409, detail="账号已注册，请直接登录")
    token = await _repository_call(_repository.create_session, created["user_id"])
    _set_session_cookie(response, token)
    return AuthResponse(**created)


@router.post("/login", response_model=AuthResponse)
async def login(request: AuthRequest, response: Response) -> AuthResponse:
    """校验账号密码并建立登录会话；统一错误信息避免泄露账号是否存在。"""
    await _ensure_repository()
    user = await _repository_call(_repository.find_user_by_account, request.account)
    if user is None or not _verify_password(request.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    token = await _repository_call(_repository.create_session, user["user_id"])
    _set_session_cookie(response, token)
    return AuthResponse(user_id=user["user_id"], username=user["account"])


@router.get("/me", response_model=AuthResponse)
async def get_current_user(request: Request) -> AuthResponse:
    """返回当前 Cookie 对应用户，前端据此在加载时校验登录状态。"""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    await _ensure_repository()
    user = await _repository_call(_repository.find_session_user, token)
    if user is None:
        raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
    return AuthResponse(**user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response) -> Response:
    """删除当前持久化会话并清除浏览器 Cookie。"""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        await _ensure_repository()
        await _repository_call(_repository.delete_session, token)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    # 直接返回注入的 Response 时，路由装饰器的 status_code 不会覆盖默认 200。
    response.status_code = 204
    return response


@router.get("/health", include_in_schema=False)
async def auth_health() -> Response:
    return Response(content="ok", media_type="text/plain")
