"""模型与 PostgreSQL 异步持久化的集中配置。"""

# ============================================================
# 模型配置
# ============================================================
import asyncio
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

# psycopg 的异步连接不支持 Windows 默认的 ProactorEventLoop。
# 应用模块在 Uvicorn 创建事件循环前加载本配置，因此在这里统一使用 Selector 策略。
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env", override=True)

# 主 Agent 模型
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL")
MAIN_MODEL = ChatDeepSeek(
    model="deepseek-v4-flash",
    extra_body={"thinking": {"type": "disabled"}},
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL,
)

# 摘要专用模型
SUMMARY_MODEL = ChatDeepSeek(
    model="deepseek-v4-flash",
    temperature=0.3,
    extra_body={"thinking": {"type": "disabled"}},
    api_key=DEEPSEEK_API_KEY,
    base_url=DEEPSEEK_BASE_URL,
)

# ============================================================
# Agent 运行保护
# ============================================================
# 限制按单次 Agent run 计数；恢复中断会开启新的 run，避免长期会话被历史调用耗尽。
MAIN_AGENT_MODEL_RUN_LIMIT = 50
MAIN_AGENT_TOOL_RUN_LIMIT = 50
SUBAGENT_MODEL_RUN_LIMIT = 50
SUBAGENT_TOOL_RUN_LIMIT = 50
ASYNC_SUBAGENT_MODEL_RUN_LIMIT = 50
# 采购分析通常要先确认图表 Schema、检索多组订单再生成交付物；16 次工具调用仍可能
# 在“查询 + 图表 + Markdown 报告”的完整流程中提前终止。提高到 32 只扩大单次运行预算，
# 不改变每次新询问重新计数的语义，也继续保留循环保护。
ASYNC_SUBAGENT_TOOL_RUN_LIMIT = 32

# ============================================================
# OpenSandbox 配置
# ============================================================
# API key 只从环境变量读取，避免把凭据写入项目文件或日志。
OPEN_SANDBOX_HOST = os.getenv("OPEN_SANDBOX_HOST", "127.0.0.1")
OPEN_SANDBOX_PORT = int(os.getenv("OPEN_SANDBOX_PORT", "18083"))
OPEN_SANDBOX_API_KEY = os.getenv("OPEN_SANDBOX_API_KEY")
# 先用 sandbox/Dockerfile 构建本地多语言镜像；默认值仅影响新建沙箱。
OPEN_SANDBOX_IMAGE = os.getenv(
    "OPEN_SANDBOX_IMAGE",
    "myagent-sandbox:1",
)
OPEN_SANDBOX_DEFAULT_TIMEOUT_SECONDS = int(
    os.getenv("OPEN_SANDBOX_DEFAULT_TIMEOUT_SECONDS", "120")
)
OPEN_SANDBOX_SANDBOX_TIMEOUT_SECONDS = int(
    os.getenv("OPEN_SANDBOX_SANDBOX_TIMEOUT_SECONDS", "86400")
)
# 启动只调度一个无用户预热实例；创建与每次访问续期共用上面的有效期。
# 预热失败退回按需创建，不启动周期保活任务。
OPEN_SANDBOX_PREWARM_ENABLED = os.getenv(
    "OPEN_SANDBOX_PREWARM_ENABLED", "true"
).lower() in {"1", "true", "yes", "on"}

# ============================================================
# Agent 文件常量
# ============================================================
# 主 Agent 只读指引文件
AGENTS_MD_FILENAME = "/AGENTS.md"
# 技能文件仅保存在项目内的受限目录。主 Agent 和每个子 Agent 使用独立子目录，
# 分配技能时会把文件从主 Agent 的暂存目录移动到对应子 Agent 的目录。
SKILLS_ROOT = Path(__file__).parent / "skills"
MAIN_SKILLS_PATH = "/skills/main/"
SUBAGENT_SKILLS_PATH = "/skills/subagents"

# ============================================================
# PostgreSQL 持久化配置
# ============================================================
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "langgraph_db")
DB_USER = os.getenv("DB_USER", "langgraph_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_SSLMODE = os.getenv("DB_SSLMODE", "disable")
POSTGRES_URI = (
    f"postgresql://{quote_plus(DB_USER)}:{quote_plus(DB_PASSWORD)}"
    f"@{DB_HOST}:{DB_PORT}/{quote_plus(DB_NAME)}"
    f"?sslmode={quote_plus(DB_SSLMODE)}"
)

async def create_async_persistence() -> tuple[Any, Any]:
    """
    创建供异步 Agent 调用使用的 PostgreSQL Store 和 Checkpointer。
    """
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.store.postgres.aio import AsyncPostgresStore
    from psycopg import AsyncConnection
    from psycopg.rows import dict_row

    # 任意建连或 setup 失败（包括取消）都回收已经创建的连接；成功后移交给 Loader。
    async with AsyncExitStack() as resources:
        store_connection = await AsyncConnection.connect(
            POSTGRES_URI, autocommit=True, prepare_threshold=0, row_factory=dict_row,
        )
        resources.push_async_callback(store_connection.close)
        checkpointer_connection = await AsyncConnection.connect(
            POSTGRES_URI, autocommit=True, prepare_threshold=0, row_factory=dict_row,
        )
        resources.push_async_callback(checkpointer_connection.close)
        store = AsyncPostgresStore(conn=store_connection)
        checkpointer = AsyncPostgresSaver(conn=checkpointer_connection)
        # setup 只维护框架表结构，不覆盖历史数据。
        await store.setup()
        await checkpointer.setup()
        resources.pop_all()
        return store, checkpointer


async def close_async_persistence(store: Any, checkpointer: Any) -> None:
    """
    关闭 Store 和 Checkpointer 各自持有的数据库连接。
    """
    # 连接由 create_async_persistence 创建，服务停止时必须成对释放。
    try:
        await checkpointer.conn.close()
    finally:
        await store.conn.close()
