package com.motorparts.dto;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * 零部件及供应商信息（嵌套在订单明细中）
 */
public class PartWithSupplier {

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
    private LocalDateTime createTime;
    private LocalDateTime updateTime;

    /**
     * 关联的供应商信息
     */
    private SupplierInfo supplier;

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

    public SupplierInfo getSupplier() {
        return supplier;
    }

    public void setSupplier(SupplierInfo supplier) {
        this.supplier = supplier;
    }

    /**
     * 供应商信息（简化版）
     */
    public static class SupplierInfo {
        private Long id;
        private String supplierCode;
        private String name;
        private String contactPerson;
        private String phone;
        private String email;
        private String address;
        private String creditRating;
        private Integer status;

        public Long getId() {
            return id;
        }

        public void setId(Long id) {
            this.id = id;
        }

        public String getSupplierCode() {
            return supplierCode;
        }

        public void setSupplierCode(String supplierCode) {
            this.supplierCode = supplierCode;
        }

        public String getName() {
            return name;
        }

        public void setName(String name) {
            this.name = name;
        }

        public String getContactPerson() {
            return contactPerson;
        }

        public void setContactPerson(String contactPerson) {
            this.contactPerson = contactPerson;
        }

        public String getPhone() {
            return phone;
        }

        public void setPhone(String phone) {
            this.phone = phone;
        }

        public String getEmail() {
            return email;
        }

        public void setEmail(String email) {
            this.email = email;
        }

        public String getAddress() {
            return address;
        }

        public void setAddress(String address) {
            this.address = address;
        }

        public String getCreditRating() {
            return creditRating;
        }

        public void setCreditRating(String creditRating) {
            this.creditRating = creditRating;
        }

        public Integer getStatus() {
            return status;
        }

        public void setStatus(Integer status) {
            this.status = status;
        }
    }
}
