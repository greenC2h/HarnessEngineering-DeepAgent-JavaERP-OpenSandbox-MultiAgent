from fastmcp import FastMCP, Context
from typing import Optional

from mcp_server.http_base import request_erp

# 分组名称
GROUP_NAME = "part"   # 分组名称，最终工具名称为 part_query / part_search
def register_parts_tools(mcp: FastMCP):
    """注册零部件分组的所有工具"""

    @mcp.tool(name=f"{GROUP_NAME}_query")
    async def query_parts(
        current: Optional[int] = 1,
        size: Optional[int] = 10,
        name: Optional[str] = None,
        category: Optional[str] = None,
        supplier_id: Optional[int] = None,
        ctx: Context = None,
    ) -> list:
        """
        分页查询零部件列表。
        支持按名称模糊查询、按分类筛选、按供应商ID筛选。

        Args:
            current: 当前页码，从1开始，默认1
            size: 每页大小，默认10
            name: 零件名称（模糊查询），可选
            category: 分类(发动机类/车架类/电气类/制动类/传动类/外观件)，可选
            supplier_id: 供应商ID，可选
        """
        http_client = ctx.request_context.lifespan_context.get("http_client")

        # 构建请求参数（过滤 None 值，映射到 API 字段名）
        request_params = {}
        if current is not None:
            request_params["current"] = current
        if size is not None:
            request_params["size"] = size
        if name is not None:
            request_params["name"] = name
        if category is not None:
            request_params["category"] = category
        if supplier_id is not None:
            request_params["supplierId"] = supplier_id

        data = await request_erp(http_client, "GET", "/parts/page", params=request_params)
        return (data or {}).get("records", [])

    @mcp.tool(name=f"{GROUP_NAME}_search")
    async def search_parts(name: str, ctx: Context) -> list:
        """
        按名称搜索零部件。
        与 part_query 不同，此接口直接搜索，name 为必填参数。

        Args:
            name: 零件名称（模糊查询），必填
        """
        http_client = ctx.request_context.lifespan_context.get("http_client")

        return await request_erp(http_client, "GET", "/parts/search", params={"name": name}) or []

    @mcp.tool(name=f"{GROUP_NAME}_by_supplier")
    async def list_parts_by_supplier(supplier_id: int, ctx: Context) -> list:
        """
        根据供应商 ID 查询该供应商下有采购记录的零配件列表。

        Args:
            supplier_id: 供应商 ID（路径参数，必填）
        """
        http_client = ctx.request_context.lifespan_context.get("http_client")

        return await request_erp(http_client, "GET", f"/parts/supplier/{supplier_id}") or []
