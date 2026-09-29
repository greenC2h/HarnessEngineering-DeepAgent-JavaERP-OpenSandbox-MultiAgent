package com.motorparts.common.enums;

/**
 * 零件分类枚举
 */
public enum PartCategoryEnum {

    /**
     * 发动机类
     */
    ENGINE("发动机类", "发动机类"),

    /**
     * 车架类
     */
    FRAME("车架类", "车架类"),

    /**
     * 电气类
     */
    ELECTRICAL("电气类", "电气类"),

    /**
     * 制动类
     */
    BRAKE("制动类", "制动类"),

    /**
     * 传动类
     */
    TRANSMISSION("传动类", "传动类"),

    /**
     * 外观件
     */
    APPEARANCE("外观件", "外观件");

    private final String code;
    private final String description;

    PartCategoryEnum(String code, String description) {
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
    public static PartCategoryEnum getByCode(String code) {
        if (code == null) {
            return null;
        }
        for (PartCategoryEnum category : values()) {
            if (category.getCode().equals(code)) {
                return category;
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