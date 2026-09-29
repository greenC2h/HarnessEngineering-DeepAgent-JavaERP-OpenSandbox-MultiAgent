package com.motorparts.entity;

/**
 * 订单明细（包含零部件详情）
 */
public class OrderDetailWithPart extends OrderDetail {

    /**
     * 零部件详情
     */
    private Part partDetail;

    public Part getPartDetail() {
        return partDetail;
    }

    public void setPartDetail(Part partDetail) {
        this.partDetail = partDetail;
    }
}