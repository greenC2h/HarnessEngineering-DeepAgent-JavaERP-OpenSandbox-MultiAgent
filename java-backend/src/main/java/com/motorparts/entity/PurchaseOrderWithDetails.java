package com.motorparts.entity;

import java.util.List;

/**
 * 采购订单（包含订单明细及零部件详情）
 */
public class PurchaseOrderWithDetails extends PurchaseOrder {

    /**
     * 订单明细列表（包含零部件详情）
     */
    private List<OrderDetailWithPart> orderDetail;

    public List<OrderDetailWithPart> getOrderDetail() {
        return orderDetail;
    }

    public void setOrderDetail(List<OrderDetailWithPart> orderDetail) {
        this.orderDetail = orderDetail;
    }
}