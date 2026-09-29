package com.motorparts.common.enums;

/**
 * 用户角色枚举
 */
public enum UserRoleEnum {

    /**
     * 管理员
     */
    ADMIN("admin", "管理员"),

    /**
     * 采购员
     */
    PURCHASE("purchase", "采购员"),

    /**
     * 仓管员
     */
    WAREHOUSE("warehouse", "仓管员"),

    /**
     * 销售员
     */
    SALES("sales", "销售员");

    private final String code;
    private final String description;

    UserRoleEnum(String code, String description) {
        this.code = code;
        this.description = description;
    }

    public String getCode() {
        return code;
    }

    public String getDescription() {
        return description;
    }

    /**
     * 根据code获取枚举
     */
    public static UserRoleEnum getByCode(String code) {
        if (code == null) {
            return null;
        }
        for (UserRoleEnum role : values()) {
            if (role.getCode().equals(code)) {
                return role;
            }
        }
        return null;
    }

    /**
     * 检查code是否存在
     */
    public static boolean isValid(String code) {
        return getByCode(code) != null;
    }
}