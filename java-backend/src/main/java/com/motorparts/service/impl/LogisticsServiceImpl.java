package com.motorparts.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.motorparts.entity.Logistics;
import com.motorparts.mapper.LogisticsMapper;
import com.motorparts.service.LogisticsService;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 物流信息服务实现类
 */
@Service
public class LogisticsServiceImpl extends ServiceImpl<LogisticsMapper, Logistics> implements LogisticsService {

    @Override
    public Page<Logistics> pageLogistics(Page<Logistics> page, Long orderId, String trackingNumber, Integer status) {
        LambdaQueryWrapper<Logistics> wrapper = new LambdaQueryWrapper<>();

        if (orderId != null) {
            wrapper.eq(Logistics::getOrderId, orderId);
        }

        if (StringUtils.hasText(trackingNumber)) {
            wrapper.like(Logistics::getTrackingNumber, trackingNumber);
        }

        if (status != null) {
            wrapper.eq(Logistics::getStatus, status);
        }

        wrapper.orderByDesc(Logistics::getCreateTime);

        return baseMapper.selectPage(page, wrapper);
    }

    @Override
    public List<Logistics> getLogisticsByOrderId(Long orderId) {
        if (orderId == null) {
            return List.of();
        }

        LambdaQueryWrapper<Logistics> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Logistics::getOrderId, orderId)
               .orderByDesc(Logistics::getCreateTime);

        return baseMapper.selectList(wrapper);
    }

    @Override
    public boolean updateStatus(Long id, Integer status) {
        if (id == null || status == null) {
            return false;
        }

        LambdaUpdateWrapper<Logistics> wrapper = new LambdaUpdateWrapper<>();
        wrapper.set(Logistics::getStatus, status)
               .eq(Logistics::getId, id);

        return update(wrapper);
    }

    @Override
    public boolean updateShippingInfo(Long id, LocalDateTime shipTime, String trackingNumber, String logisticsCompany) {
        if (id == null || shipTime == null || !StringUtils.hasText(trackingNumber)) {
            return false;
        }

        LambdaUpdateWrapper<Logistics> wrapper = new LambdaUpdateWrapper<>();
        wrapper.set(Logistics::getShipTime, shipTime)
               .set(Logistics::getTrackingNumber, trackingNumber)
               .set(Logistics::getLogisticsCompany, logisticsCompany)
               .set(Logistics::getStatus, 2) // 运输中
               .eq(Logistics::getId, id);

        return update(wrapper);
    }

    @Override
    public boolean updateReceivingInfo(Long id, LocalDateTime actualArrivalTime, String receiver) {
        if (id == null || actualArrivalTime == null || !StringUtils.hasText(receiver)) {
            return false;
        }

        LambdaUpdateWrapper<Logistics> wrapper = new LambdaUpdateWrapper<>();
        wrapper.set(Logistics::getActualArrivalTime, actualArrivalTime)
               .set(Logistics::getReceiver, receiver)
               .set(Logistics::getStatus, 3) // 已签收
               .eq(Logistics::getId, id);

        return update(wrapper);
    }
}