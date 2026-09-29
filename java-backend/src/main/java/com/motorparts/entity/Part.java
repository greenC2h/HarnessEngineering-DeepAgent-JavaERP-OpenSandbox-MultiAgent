package com.motorparts.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.math.BigDecimal;

/**
 * 产品/零部件实体类
 */
@TableName("part")
public class Part extends BaseEntity {

    /**
     * 零部件ID
     */
    @TableId(type = IdType.AUTO)
    private Long id;

    /**
     * 零件编码
     */
    @NotBlank(message = "零件编码不能为空")
    @TableField("part_code")
    private String partCode;

    /**
     * 零件名称
     */
    @NotBlank(message = "零件名称不能为空")
    private String name;

    /**
     * 型号
     */
    private String model;

    /**
     * 规格
     */
    private String specification;

    /**
     * 单位（个/套/件/台等）
     */
    private String unit;

    /**
     * 采购单价
     */
    @NotNull(message = "采购单价不能为空")
    @DecimalMin(value = "0.00", message = "采购单价不能小于0")
    @TableField("purchase_price")
    private BigDecimal purchasePrice;

    /**
     * 建议零售价
     */
    @TableField("suggested_retail_price")
    private BigDecimal suggestedRetailPrice;

    /**
     * 库存预警值
     */
    @TableField("stock_warning_value")
    private Integer stockWarningValue;

    /**
     * 供应商ID
     */
    @TableField("supplier_id")
    private Long supplierId;

    /**
     * 分类
     * 发动机类、车架类、电气类、制动类、传动类、外观件
     */
    private String category;

    /**
     * 零件描述
     */
    private String description;

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

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || getClass() != o.getClass()) return false;
        Part part = (Part) o;
        return id != null && id.equals(part.id);
    }

    @Override
    public int hashCode() {
        return getClass().hashCode();
    }
}