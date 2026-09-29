from fastmcp import FastMCP
from mcp_server.http_base import mcp_lifespan
from mcp_server.server_config import MCP_HOST, MCP_PORT, MCP_PATH


# 创建 FastMCP 实例，注入生命周期管理器
mcp = FastMCP(
    name="Java-Backend-MCP-Server",
    instructions="调用 Java 后端 REST API 的工具集，支持按业务分组访问",
    version="1.0.0",
    lifespan=mcp_lifespan # 关键配置
)

# 导入各个分组的注册函数
from mcp_server.tools.suppliers_tools import register_supplier_tools
from mcp_server.tools.parts_tools import register_parts_tools
from mcp_server.tools.order_tools import register_order_tools
from mcp_server.tools.inventory_tools import register_inventory_tools


# 注册所有分组
register_supplier_tools(mcp)
register_parts_tools(mcp)
register_order_tools(mcp)
register_inventory_tools(mcp)


def main():

    # 启动 Streamable HTTP 服务
    mcp.run(
        transport="streamable-http",
        host=MCP_HOST,
        port=MCP_PORT,
        path=MCP_PATH
    )
    # 注意：run() 会阻塞，且 lifespan 会在服务器关闭时自动清理资源


if __name__ == "__main__":
    main()