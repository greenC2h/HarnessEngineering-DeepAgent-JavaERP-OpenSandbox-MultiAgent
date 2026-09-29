"""Java ERP MCP 服务的连接与监听配置。"""

import os


# Java 服务可由统一启动器或独立进程管理；此服务只通过 HTTP 调用其 REST API。
JAVA_API_BASE_URL = os.getenv("JAVA_API_BASE_URL", "http://127.0.0.1:18080/api")

# 18000 由 MotoParts Agent ERP 的 FastAPI 后端、18080 由 Java 服务使用，MCP 适配层必须使用独立端口。
MCP_HOST = os.getenv("MYAGENT_MCP_HOST", "127.0.0.1")
MCP_PORT = int(os.getenv("MYAGENT_MCP_PORT", "18081"))
MCP_PATH = os.getenv("MYAGENT_MCP_PATH", "/mcp")
