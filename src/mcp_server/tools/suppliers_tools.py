from fastmcp import FastMCP, Context

from mcp_server.http_base import request_erp

# 分组名称
GROUP_NAME = "supplier"
def register_supplier_tools(mcp: FastMCP):
    """注册供应商分组的所有工具"""

    @mcp.tool(name=f"{GROUP_NAME}_query")
    async def query_suppliers(name: str, ctx: Context) -> list:
        """
        按名称模糊搜索供应商。

        Args:
            name: 供应商名称（模糊查询），必填
        """
        http_client = ctx.request_context.lifespan_context.get("http_client")
        request_params = {"name": name}

        return await request_erp(http_client, "GET", "/suppliers/search", params=request_params) or []
