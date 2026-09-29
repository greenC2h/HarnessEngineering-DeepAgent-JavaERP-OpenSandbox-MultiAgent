package com.motorparts.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 库存信息（含零部件详情）
 */
public class InventoryWithPart {

    private Long id;
    private Long partId;
    private Integer currentQuantity;
    private Integer safetyStock;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime lastInboundTime;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private LocalDateTime lastOutboundTime;

    private String warehouseLocation;
    private Integer deleted;

    @JsonFormat(pattern = "yyyy-MM-dd'T'HH:mm:ss.SSS")
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd'T'HH:mm:ss.SSS")
    private LocalDateTime updateTime;

    /**
     * 关联的零部件信息
     */
    private PartInfo partDetail;

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

    public Integer getDeleted() {
        return deleted;
    }

    public void setDeleted(Integer deleted) {
        this.deleted = deleted;
    }

    public LocalDateTime getCreateTime() {
        return createTime;
    }

    public void setCreateTime(LocalDateTime createTime) {
        this.createTime = createTime;
    }

    public LocalDateTime getUpdateTime() {
        return updateTime;
    }

    public void setUpdateTime(LocalDateTime updateTime) {
        this.updateTime = updateTime;
    }

    public PartInfo getPartDetail() {
        return partDetail;
    }

    public void setPartDetail(PartInfo partDetail) {
        this.partDetail = partDetail;
    }

    /**
     * 零部件信息（用于嵌套展示）
     */
    public static class PartInfo {
        private Long id;
        private String partCode;
        private String name;
        private String model;
        private String specification;
        private String unit;
        private BigDecimal purchasePrice;
        private BigDecimal suggestedRetailPrice;
        private Integer stockWarningValue;
        private Long supplierId;
        private String category;
        private String description;
        private Integer deleted;

        @JsonFormat(pattern = "yyyy-MM-dd'T'HH:mm:ss.SSS")
        private LocalDateTime createTime;

        @JsonFormat(pattern = "yyyy-MM-dd'T'HH:mm:ss.SSS")
        private LocalDateTime updateTime;

        public Long getId() {
            return id;
        }

        public void setId(Long id) {
            this.id = id;
        }

        public String getPartCode() {
            return partCode;
        }

        public void setPartCode(String partCode) {
            this.partCode = partCode;
        }

        public String getName() {
            return name;
        }

        public void setName(String name) {
            this.name = name;
        }

        public String getModel() {
            return model;
        }

        public void setModel(String model) {
            this.model = model;
        }

        public String getSpecification() {
            return specification;
        }

        public void setSpecification(String specification) {
            this.specification = specification;
        }

        public String getUnit() {
            return unit;
        }

        public void setUnit(String unit) {
            this.unit = unit;
        }

        public BigDecimal getPurchasePrice() {
            return purchasePrice;
        }

        public void setPurchasePrice(BigDecimal purchasePrice) {
            this.purchasePrice = purchasePrice;
        }

        public BigDecimal getSuggestedRetailPrice() {
            return suggestedRetailPrice;
        }

        public void setSuggestedRetailPrice(BigDecimal suggestedRetailPrice) {
            this.suggestedRetailPrice = suggestedRetailPrice;
        }

        public Integer getStockWarningValue() {
            return stockWarningValue;
        }

        public void setStockWarningValue(Integer stockWarningValue) {
            this.stockWarningValue = stockWarningValue;
        }

        public Long getSupplierId() {
            return supplierId;
        }

        public void setSupplierId(Long supplierId) {
            this.supplierId = supplierId;
        }

        public String getCategory() {
            return category;
        }

        public void setCategory(String category) {
            this.category = category;
        }

        public String getDescription() {
            return description;
        }

        public void setDescription(String description) {
            this.description = description;
        }

        public Integer getDeleted() {
            return deleted;
        }

        public void setDeleted(Integer deleted) {
            this.deleted = deleted;
        }

        public LocalDateTime getCreateTime() {
            return createTime;
        }

        public void setCreateTime(LocalDateTime createTime) {
            this.createTime = createTime;
        }

        public LocalDateTime getUpdateTime() {
            return updateTime;
        }

        public void setUpdateTime(LocalDateTime updateTime) {
            this.updateTime = updateTime;
        }
    }
}
