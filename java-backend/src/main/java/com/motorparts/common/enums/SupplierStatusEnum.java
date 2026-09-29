package com.motorparts.common.enums;

/**
 * 供应商状态枚举
 */
public enum SupplierStatusEnum {

    /**
     * 合作中
     */
    COOPERATING(1, "合作中"),

    /**
     * 已终止
     */
    TERMINATED(2, "已终止"),

    /**
     * 审核中
     */
    REVIEWING(3, "审核中");

    private final Integer code;
    private final String description;

    SupplierStatusEnum(Integer code, String description) {
        this.code = code;
        this.description = description;
    }

    public Integer getCode() {
        return code;
    }

    public String getDescription() {
        return description;
    }

    /**
     * 根据code获取枚举
     */
    public static SupplierStatusEnum getByCode(Integer code) {
        if (code == null) {
            return null;
        }
        for (SupplierStatusEnum status : values()) {
            if (status.getCode().equals(code)) {
                return status;
            }
        }
        return null;
    }

    /**
     * 检查code是否存在
     */
    public static boolean isValid(Integer code) {
        return getByCode(code) != null;
    }
}