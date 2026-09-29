package com.motorparts.common.enums;

/**
 * 响应码枚举
 */
public enum ResultCode {

    /**
     * 成功
     */
    SUCCESS(200, "操作成功"),

    /**
     * 失败
     */
    ERROR(500, "操作失败"),

    /**
     * 参数错误
     */
    PARAM_ERROR(400, "参数错误"),

    /**
     * 未授权
     */
    UNAUTHORIZED(401, "未授权"),

    /**
     * 禁止访问
     */
    FORBIDDEN(403, "禁止访问"),

    /**
     * 资源不存在
     */
    NOT_FOUND(404, "资源不存在"),

    /**
     * 服务器内部错误
     */
    SERVER_ERROR(500, "服务器内部错误"),

    /**
     * 业务异常
     */
    BUSINESS_ERROR(600, "业务异常"),

    /**
     * 数据已存在
     */
    DATA_EXISTS(601, "数据已存在"),

    /**
     * 数据不存在
     */
    DATA_NOT_EXISTS(602, "数据不存在"),

    /**
     * 库存不足
     */
    INSUFFICIENT_INVENTORY(603, "库存不足"),

    /**
     * 订单状态异常
     */
    ORDER_STATUS_ERROR(604, "订单状态异常"),

    /**
     * 供应商状态异常
     */
    SUPPLIER_STATUS_ERROR(605, "供应商状态异常");

    /**
     * 响应码
     */
    private final Integer code;

    /**
     * 响应消息
     */
    private final String message;

    ResultCode(Integer code, String message) {
        this.code = code;
        this.message = message;
    }

    public Integer getCode() {
        return code;
    }

    public String getMessage() {
        return message;
    }
}