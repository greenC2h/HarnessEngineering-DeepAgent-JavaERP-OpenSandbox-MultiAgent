package com.motorparts.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.databind.annotation.JsonDeserialize;

import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import java.time.LocalDateTime;

/**
 * 库存实体类
 */
@TableName("inventory")
public class Inventory extends BaseEntity {

    /**
     * 库存ID
     */
    @TableId(type = IdType.AUTO)
    private Long id;

    /**
     * 零部件ID
     */
    @NotNull(message = "零部件ID不能为空")
    @TableField("part_id")
    private Long partId;

    /**
     * 当前库存数量
     */
    @NotNull(message = "当前库存数量不能为空")
    @Min(value = 0, message = "库存数量不能小于0")
    @TableField("current_quantity")
    private Integer currentQuantity;

    /**
     * 安全库存量
     */
    @TableField("safety_stock")
    private Integer safetyStock;

    /**
     * 最近入库时间
     */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    @JsonDeserialize(using = com.motorparts.common.CustomLocalDateTimeDeserializer.class)
    @TableField("last_inbound_time")
    private LocalDateTime lastInboundTime;

    /**
     * 最近出库时间
     */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    @JsonDeserialize(using = com.motorparts.common.CustomLocalDateTimeDeserializer.class)
    @TableField("last_outbound_time")
    private LocalDateTime lastOutboundTime;

    /**
     * 仓库位置
     */
    @TableField("warehouse_location")
    private String warehouseLocation;

    public Inventory() {
    }

    public static Builder builder() {
        return new Builder();
    }

    public static class Builder {
        private Long partId;
        private Integer currentQuantity;
        private Integer safetyStock;
        private LocalDateTime lastInboundTime;
        private LocalDateTime lastOutboundTime;
        private String warehouseLocation;

        public Builder partId(Long partId) {
            this.partId = partId;
            return this;
        }

        public Builder currentQuantity(Integer currentQuantity) {
            this.currentQuantity = currentQuantity;
            return this;
        }

        public Builder safetyStock(Integer safetyStock) {
            this.safetyStock = safetyStock;
            return this;
        }

        public Builder lastInboundTime(LocalDateTime lastInboundTime) {
            this.lastInboundTime = lastInboundTime;
            return this;
        }

        public Builder lastOutboundTime(LocalDateTime lastOutboundTime) {
            this.lastOutboundTime = lastOutboundTime;
            return this;
        }

        public Builder warehouseLocation(String warehouseLocation) {
            this.warehouseLocation = warehouseLocation;
            return this;
        }

        public Inventory build() {
            Inventory inventory = new Inventory();
            inventory.setPartId(this.partId);
            inventory.setCurrentQuantity(this.currentQuantity);
            inventory.setSafetyStock(this.safetyStock);
            inventory.setLastInboundTime(this.lastInboundTime);
            inventory.setLastOutboundTime(this.lastOutboundTime);
            inventory.setWarehouseLocation(this.warehouseLocation);
            return inventory;
        }
    }

    public Long getId() {
        return id;
    }

    public void setId(Long id) {
        this.id = id;
    }

    public Long getPartId() {
        return partId;
    }

    public void setPartId(Long partId) {
        this.partId = partId;
    }

    public Integer getCurrentQuantity() {
        return currentQuantity;
    }

    public void setCurrentQuantity(Integer currentQuantity) {
        this.currentQuantity = currentQuantity;
    }

    public Integer getSafetyStock() {
        return safetyStock;
    }

    public void setSafetyStock(Integer safetyStock) {
        this.safetyStock = safetyStock;
    }

    public LocalDateTime getLastInboundTime() {
        return lastInboundTime;
    }

    public void setLastInboundTime(LocalDateTime lastInboundTime) {
        this.lastInboundTime = lastInboundTime;
    }

    public LocalDateTime getLastOutboundTime() {
        return lastOutboundTime;
    }

    public void setLastOutboundTime(LocalDateTime lastOutboundTime) {
        this.lastOutboundTime = lastOutboundTime;
    }

    public String getWarehouseLocation() {
        return warehouseLocation;
    }

    public void setWarehouseLocation(String warehouseLocation) {
        this.warehouseLocation = warehouseLocation;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || getClass() != o.getClass()) return false;
        Inventory inventory = (Inventory) o;
        return id != null && id.equals(inventory.id);
    }

    @Override
    public int hashCode() {
        return getClass().hashCode();
    }
}