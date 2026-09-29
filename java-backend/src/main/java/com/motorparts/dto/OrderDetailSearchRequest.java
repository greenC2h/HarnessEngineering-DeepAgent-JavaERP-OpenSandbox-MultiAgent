package com.motorparts.dto;

import java.time.LocalDate;

/**
 * 采购订单明细搜索请求参数
 */
public class OrderDetailSearchRequest {

    /**
     * 零部件名称（模糊匹配）
     */
    private String partName;

    /**
     * 开始日期（订单时间在此之后）
     */
    private LocalDate startDate;

    /**
     * 结束日期（订单时间在此之前）
     */
    private LocalDate endDate;

    public String getPartName() {
        return partName;
    }

    public void setPartName(String partName) {
        this.partName = partName;
    }

    public LocalDate getStartDate() {
        return startDate;
    }

    public void setStartDate(LocalDate startDate) {
        this.startDate = startDate;
    }

    public LocalDate getEndDate() {
        return endDate;
    }

    public void setEndDate(LocalDate endDate) {
        this.endDate = endDate;
    }
}
