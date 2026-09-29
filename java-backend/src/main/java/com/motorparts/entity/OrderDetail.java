package com.motorparts.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import java.math.BigDecimal;

/**
 * 订单明细实体类
 */
@TableName("order_detail")
public class OrderDetail extends BaseEntity {

    /**
     * 明细ID（应用层生成，非自增）
     */
    @TableId(type = IdType.INPUT)
    private Long id;

    /**
     * 订单ID
     */
    @NotNull(message = "订单ID不能为空")
    @TableField("order_id")
    private Long orderId;

    /**
     * 零部件ID
     */
    @NotNull(message = "零部件ID不能为空")
    @TableField("part_id")
    private Long partId;

    /**
     * 采购数量
     */
    @NotNull(message = "采购数量不能为空")
    @Min(value = 1, message = "采购数量至少为1")
    private Integer quantity;

    /**
     * 采购单价
     */
    @NotNull(message = "采购单价不能为空")
    @TableField("unit_price")
    private BigDecimal unitPrice;

    /**
     * 小计金额（数据库计算字段）
     */
    @TableField("subtotal")
    private BigDecimal subtotal;

    /**
     * 备注
     */
    private String remark;

    public OrderDetail() {
    }

    public static Builder builder() {
        return new Builder();
    }

    public static class Builder {
        private Long id;
        private Long orderId;
        private Long partId;
        private Integer quantity;
        private BigDecimal unitPrice;
        private BigDecimal subtotal;
        private String remark;

        public Builder id(Long id) {
            this.id = id;
            return this;
        }

        public Builder orderId(Long orderId) {
            this.orderId = orderId;
            return this;
        }

        public Builder partId(Long partId) {
            this.partId = partId;
            return this;
        }

        public Builder quantity(Integer quantity) {
            this.quantity = quantity;
            return this;
        }

        public Builder unitPrice(BigDecimal unitPrice) {
            this.unitPrice = unitPrice;
            return this;
        }

        public Builder subtotal(BigDecimal subtotal) {
            this.subtotal = subtotal;
            return this;
        }

        public Builder remark(String remark) {
            this.remark = remark;
            return this;
        }

        public OrderDetail build() {
            OrderDetail detail = new OrderDetail();
            detail.setId(this.id);
            detail.setOrderId(this.orderId);
            detail.setPartId(this.partId);
            detail.setQuantity(this.quantity);
            detail.setUnitPrice(this.unitPrice);
            detail.setSubtotal(this.subtotal);
            detail.setRemark(this.remark);
            return detail;
        }
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public Long getOrderId() {
        return orderId;
    }

    public void setOrderId(Long orderId) {
        this.orderId = orderId;
    }

    public Long getPartId() {
        return partId;
    }

    public void setPartId(Long partId) {
        this.partId = partId;
    }

    public Integer getQuantity() {
        return quantity;
    }

    public void setQuantity(Integer quantity) {
        this.quantity = quantity;
    }

    public BigDecimal getUnitPrice() {
        return unitPrice;
    }

    public void setUnitPrice(BigDecimal unitPrice) {
        this.unitPrice = unitPrice;
    }

    public BigDecimal getSubtotal() {
        return subtotal;
    }

    public void setSubtotal(BigDecimal subtotal) {
        this.subtotal = subtotal;
    }

    public String getRemark() {
        return remark;
    }

    public void setRemark(String remark) {
        this.remark = remark;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || getClass() != o.getClass()) return false;
        OrderDetail that = (OrderDetail) o;
        return id != null && id.equals(that.id);
    }

    @Override
    public int hashCode() {
        return getClass().hashCode();
    }
}