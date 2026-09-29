from fastmcp import FastMCP, Context

from mcp_server.http_base import request_erp

GROUP_NAME = "inventory"


def register_inventory_tools(mcp: FastMCP):
    """注册库存管理分组的所有工具"""

    @mcp.tool(name=f"{GROUP_NAME}_warning")
    async def list_inventory_warnings(ctx: Context) -> list:
        """
        查询库存预警列表。
        返回所有库存不足（当前库存低于安全库存）的物料及对应的零部件详情。

        无需传参。
        """
        http_client = ctx.request_context.lifespan_context.get("http_client")

        return await request_erp(http_client, "GET", "/inventory/warning") or []
