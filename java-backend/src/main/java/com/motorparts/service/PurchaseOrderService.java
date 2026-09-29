package com.motorparts.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.IService;
import com.motorparts.dto.OrderDetailWithPartAndSupplier;
import com.motorparts.entity.PurchaseOrder;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 采购订单服务接口
 */
public interface PurchaseOrderService extends IService<PurchaseOrder> {

    /**
     * 分页查询采购订单
     *
     * @param page     分页参数
     * @param orderNumber 订单编号（可选）
     * @param status   订单状态（可选）
     * @param startDate 开始日期（可选）
     * @param endDate   结束日期（可选）
     * @return 分页结果
     */
    Page<PurchaseOrder> pageOrders(Page<PurchaseOrder> page, String orderNumber,
                                   Integer status, LocalDate startDate, LocalDate endDate);

    /**
     * 创建采购订单（包含订单明细）
     *
     * @param order 订单信息
     * @return 是否成功
     */
    boolean createOrder(PurchaseOrder order);

    /**
     * 更新订单状态
     *
     * @param id     订单ID
     * @param status 新状态
     * @return 是否成功
     */
    boolean updateOrderStatus(Long id, Integer status);

    /**
     * 获取订单统计信息
     *
     * @param startDate 开始日期
     * @param endDate   结束日期
     * @return 统计结果
     */
    OrderStatistics getOrderStatistics(LocalDate startDate, LocalDate endDate);

    /**
     * 订单统计结果
     */
    interface OrderStatistics {
        long getTotalOrders();
        long getTotalAmount();
        long getCompletedOrders();
        long getPendingOrders();
    }

    /**
     * 根据零部件名称和时间范围搜索订单明细
     *
     * @param partName   零部件名称（模糊匹配，可为null）
     * @param startDate  开始时间（订单时间在此之后，可为null）
     * @param endDate    结束时间（订单时间在此之前，可为null）
     * @return 符合条件的订单明细列表（含零部件及供应商嵌套信息）
     */
    List<OrderDetailWithPartAndSupplier> searchOrderDetails(String partName, LocalDateTime startDate, LocalDateTime endDate);
}