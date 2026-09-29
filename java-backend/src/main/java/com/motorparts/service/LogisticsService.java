package com.motorparts.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.IService;
import com.motorparts.entity.Logistics;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 物流信息服务接口
 */
public interface LogisticsService extends IService<Logistics> {

    /**
     * 分页查询物流信息
     *
     * @param page     分页参数
     * @param orderId  订单ID（可选）
     * @param trackingNumber 运单号（可选）
     * @param status   物流状态（可选）
     * @return 分页结果
     */
    Page<Logistics> pageLogistics(Page<Logistics> page, Long orderId, String trackingNumber, Integer status);

    /**
     * 根据订单ID获取物流信息
     *
     * @param orderId 订单ID
     * @return 物流信息列表
     */
    List<Logistics> getLogisticsByOrderId(Long orderId);

    /**
     * 更新物流状态
     *
     * @param id     物流ID
     * @param status 新状态
     * @return 是否成功
     */
    boolean updateStatus(Long id, Integer status);

    /**
     * 更新发货信息
     *
     * @param id           物流ID
     * @param shipTime     发货时间
     * @param trackingNumber 运单号
     * @param logisticsCompany 物流公司
     * @return 是否成功
     */
    boolean updateShippingInfo(Long id, LocalDateTime shipTime, String trackingNumber, String logisticsCompany);

    /**
     * 更新收货信息
     *
     * @param id                物流ID
     * @param actualArrivalTime 实际到达时间
     * @param receiver          收货人
     * @return 是否成功
     */
    boolean updateReceivingInfo(Long id, LocalDateTime actualArrivalTime, String receiver);
}