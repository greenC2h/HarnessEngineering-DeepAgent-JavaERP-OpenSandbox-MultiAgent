import random
from datetime import datetime
from decimal import Decimal

from fastmcp import FastMCP, Context

from typing import Optional, List

from mcp_server.http_base import request_erp

GROUP_NAME = "order"


def _generate_order_number() -> str:
    """生成订单编号：PO + 年月日(8位) + 3位随机数字"""
    today = datetime.now().strftime("%Y%m%d")
    suffix = str(random.randint(0, 999)).zfill(3)
    return f"PO{today}{suffix}"


def _prepare_request(data: dict, *, generate_defaults: bool) -> dict:
    """按操作类型填充创建默认值，并序列化 Java API 请求体。"""
    if generate_defaults:
        # 创建订单时缺少这两个必填业务字段才使用本地默认值；更新不能改写它们。
        if not data.get("orderNumber"):
            data["orderNumber"] = _generate_order_number()
        if not data.get("orderTime"):
            now = datetime.now()
            data["orderTime"] = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}"

    # 递归序列化
    return _serialize_request(data)


def _serialize_request(data: dict) -> dict:
    """递归处理：Decimal → float，date/datetime → ISO 字符串"""
    for key, value in data.items():
        if isinstance(value, Decimal):
            data[key] = float(value)
        elif hasattr(value, "isoformat"):
            data[key] = value.isoformat()
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _serialize_request(item)
        elif isinstance(value, dict):
            _serialize_request(value)
    return data


def register_order_tools(mcp: FastMCP):
    """注册订单分组的所有工具"""

    @mcp.tool(name=f"{GROUP_NAME}_create")
    async def create_order(
        order_detail: List[dict],
        order_number: Optional[str] = None,
        total_amount: Optional[float] = None,
        status: Optional[int] = None,
        order_time: Optional[str] = None,
        expected_delivery_date: Optional[str] = None,
        actual_delivery_date: Optional[str] = None,
        created_by: Optional[int] = None,
        remark: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """
        创建采购订单（POST /orders/create）。

        orderNumber 不传则自动生成（规则：PO+年月日+3位随机数字）。
        orderTime 不传则默认当前时间（格式：yyyy-MM-ddTHH:mm:ss.SSS）。
        orderDetail 必填，至少包含一个明细项；每项需提供 partId、quantity、unitPrice。

        Args:
            order_detail: 订单明细列表，每项需提供 partId, quantity, unitPrice，可选 subtotal, remark
            order_number: 订单编号（唯一标识），不传则自动生成
            total_amount: 订单总金额，不传则自动根据明细计算
            status: 订单状态(1-待审核, 2-已审核, 3-采购中, 4-已入库, 5-已取消)，默认1
            order_time: 下单时间，格式 yyyy-MM-ddTHH:mm:ss.SSS，不传则默认当前时间
            expected_delivery_date: 预计交货日期，格式 yyyy-MM-dd
            actual_delivery_date: 实际交货日期，格式 yyyy-MM-dd
            created_by: 创建人 ID
            remark: 备注
        """
        http_client = ctx.request_context.lifespan_context.get("http_client")

        # 构建请求体（映射到 API 字段名）
        request_data = {}
        if order_number is not None:
            request_data["orderNumber"] = order_number
        if total_amount is not None:
            request_data["totalAmount"] = total_amount
        if status is not None:
            request_data["status"] = status
        if order_time is not None:
            request_data["orderTime"] = order_time
        if expected_delivery_date is not None:
            request_data["expectedDeliveryDate"] = expected_delivery_date
        if actual_delivery_date is not None:
            request_data["actualDeliveryDate"] = actual_delivery_date
        if created_by is not None:
            request_data["createdBy"] = created_by
        if remark is not None:
            request_data["remark"] = remark
        if order_detail is not None:
            request_data["orderDetail"] = order_detail

        request_data = _prepare_request(request_data, generate_defaults=True)

        return await request_erp(http_client, "POST", "/orders/create", json=request_data) or {}

    @mcp.tool(name=f"{GROUP_NAME}_update")
    async def update_order(
        order_id: int,
        order_detail: Optional[List[dict]] = None,
        order_number: Optional[str] = None,
        total_amount: Optional[float] = None,
        status: Optional[int] = None,
        order_time: Optional[str] = None,
        expected_delivery_date: Optional[str] = None,
        actual_delivery_date: Optional[str] = None,
        created_by: Optional[int] = None,
        remark: Optional[str] = None,
        ctx: Context = None,
    ) -> dict:
        """
        更新采购订单（PUT /orders/update/{id}）。

        orderDetail 为可选，传入则替换原有明细。
        其他字段与创建订单格式一致。

        Args:
            order_id: 订单 ID（路径参数，必填）
            order_detail: 订单明细列表（可选），每项需提供 partId, quantity, unitPrice
            order_number: 订单编号
            total_amount: 订单总金额
            status: 订单状态(1-待审核, 2-已审核, 3-采购中, 4-已入库, 5-已取消)
            order_time: 下单时间
            expected_delivery_date: 预计交货日期
            actual_delivery_date: 实际交货日期
            created_by: 创建人 ID
            remark: 备注
        """
        http_client = ctx.request_context.lifespan_context.get("http_client")

        # 构建请求体（映射到 API 字段名，只包含非 None 字段）
        request_data = {}
        if order_number is not None:
            request_data["orderNumber"] = order_number
        if total_amount is not None:
            request_data["totalAmount"] = total_amount
        if status is not None:
            request_data["status"] = status
        if order_time is not None:
            request_data["orderTime"] = order_time
        if expected_delivery_date is not None:
            request_data["expectedDeliveryDate"] = expected_delivery_date
        if actual_delivery_date is not None:
            request_data["actualDeliveryDate"] = actual_delivery_date
        if created_by is not None:
            request_data["createdBy"] = created_by
        if remark is not None:
            request_data["remark"] = remark
        if order_detail is not None:
            request_data["orderDetail"] = order_detail

        request_data = _prepare_request(request_data, generate_defaults=False)

        return await request_erp(http_client, "PUT", f"/orders/update/{order_id}", json=request_data) or {}

    @mcp.tool(name=f"{GROUP_NAME}_search_details")
    async def search_order_details(
        part_name: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        ctx: Context = None,
    ) -> list:
        """
        搜索采购订单明细。

        支持按零部件名称、日期范围筛选，所有参数均为可选。
        返回的每条明细包含零部件详情（partDetail）及供应商信息（supplier）。

        Args:
            part_name: 零部件名称（模糊查询），可选
            start_date: 开始日期（yyyy-MM-dd 格式），可选
            end_date: 结束日期（yyyy-MM-dd 格式），可选
        """
        http_client = ctx.request_context.lifespan_context.get("http_client")

        # 构建请求参数（过滤 None 值，映射到 API 字段名）
        request_params = {}
        if part_name is not None:
            request_params["partName"] = part_name
        if start_date is not None:
            request_params["startDate"] = start_date
        if end_date is not None:
            request_params["endDate"] = end_date

        return await request_erp(http_client, "GET", "/orders/search-details", params=request_params) or []
