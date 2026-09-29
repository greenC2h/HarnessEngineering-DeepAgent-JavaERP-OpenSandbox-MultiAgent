package com.motorparts.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.motorparts.dto.OrderDetailWithPartAndSupplier;
import com.motorparts.dto.PartWithSupplier;
import com.motorparts.entity.OrderDetail;
import com.motorparts.entity.OrderDetailWithPart;
import com.motorparts.entity.Part;
import com.motorparts.entity.PurchaseOrder;
import com.motorparts.entity.PurchaseOrderWithDetails;
import com.motorparts.entity.Supplier;
import com.motorparts.mapper.OrderDetailMapper;
import com.motorparts.mapper.PartMapper;
import com.motorparts.mapper.PurchaseOrderMapper;
import com.motorparts.mapper.SupplierMapper;
import com.motorparts.service.PurchaseOrderService;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 采购订单服务实现类
 */
@Service
@RequiredArgsConstructor
public class PurchaseOrderServiceImpl extends ServiceImpl<PurchaseOrderMapper, PurchaseOrder> implements PurchaseOrderService {

    private final OrderDetailMapper orderDetailMapper;
    private final PartMapper partMapper;
    private final SupplierMapper supplierMapper;

    @Override
    public Page<PurchaseOrder> pageOrders(Page<PurchaseOrder> page, String orderNumber,
                                          Integer status, LocalDate startDate, LocalDate endDate) {
        LambdaQueryWrapper<PurchaseOrder> wrapper = new LambdaQueryWrapper<>();

        if (StringUtils.hasText(orderNumber)) {
            wrapper.like(PurchaseOrder::getOrderNumber, orderNumber);
        }

        if (status != null) {
            wrapper.eq(PurchaseOrder::getStatus, status);
        }

        if (startDate != null) {
            wrapper.ge(PurchaseOrder::getOrderTime, startDate.atStartOfDay());
        }

        if (endDate != null) {
            wrapper.le(PurchaseOrder::getOrderTime, endDate.plusDays(1).atStartOfDay());
        }

        wrapper.orderByDesc(PurchaseOrder::getOrderTime);

        return baseMapper.selectPage(page, wrapper);
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public boolean createOrder(PurchaseOrder order) {
        if (order == null || !StringUtils.hasText(order.getOrderNumber())) {
            return false;
        }

        // 检查订单编号是否已存在
        LambdaQueryWrapper<PurchaseOrder> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(PurchaseOrder::getOrderNumber, order.getOrderNumber());
        if (baseMapper.selectCount(wrapper) > 0) {
            return false;
        }

        // 设置默认值
        if (order.getOrderTime() == null) {
            order.setOrderTime(LocalDateTime.now());
        }

        if (order.getStatus() == null) {
            order.setStatus(1); // 待审核
        }

        // 计算总金额
        BigDecimal totalAmount = BigDecimal.ZERO;
        if (order instanceof PurchaseOrderWithDetails) {
            PurchaseOrderWithDetails orderWithDetails = (PurchaseOrderWithDetails) order;
            List<OrderDetailWithPart> detailParts = orderWithDetails.getOrderDetail();
            if (detailParts != null && !detailParts.isEmpty()) {
                for (OrderDetailWithPart detailWithPart : detailParts) {
                    if (detailWithPart.getQuantity() != null && detailWithPart.getUnitPrice() != null) {
                        totalAmount = totalAmount.add(
                            detailWithPart.getUnitPrice().multiply(BigDecimal.valueOf(detailWithPart.getQuantity())));
                    }
                }
            }
        }
        order.setTotalAmount(totalAmount);

        // 手动设置deleted、createTime、updateTime字段
        order.setDeleted(0);
        order.setCreateTime(LocalDateTime.now());
        order.setUpdateTime(LocalDateTime.now());

        // 保存订单
        if (!save(order)) {
            return false;
        }

        // 获取订单明细列表并保存
        if (order instanceof PurchaseOrderWithDetails) {
            PurchaseOrderWithDetails orderWithDetails = (PurchaseOrderWithDetails) order;
            List<OrderDetailWithPart> detailParts = orderWithDetails.getOrderDetail();
            if (detailParts != null && !detailParts.isEmpty()) {
                for (OrderDetailWithPart detailWithPart : detailParts) {
                    // 创建纯OrderDetail对象用于插入，避免partDetail字段干扰
                    OrderDetail detail = OrderDetail.builder()
                            .orderId(order.getId())
                            .partId(detailWithPart.getPartId())
                            .quantity(detailWithPart.getQuantity())
                            .unitPrice(detailWithPart.getUnitPrice())
                            .remark(detailWithPart.getRemark())
                            .build();
                    // 手动设置deleted、createTime、updateTime字段
                    detail.setDeleted(0);
                    detail.setCreateTime(LocalDateTime.now());
                    detail.setUpdateTime(LocalDateTime.now());
                    orderDetailMapper.insert(detail);
                }
            }
        }

        return true;
    }

    @Override
    @Transactional(rollbackFor = Exception.class)
    public boolean updateById(PurchaseOrder order) {
        if (order == null || order.getId() == null) {
            return false;
        }

        Long orderId = order.getId();

        PurchaseOrder existing = baseMapper.selectById(orderId);
        if (existing == null) {
            return false;
        }

        // orderDetail 为 null 表示部分更新，保留原明细；传入空数组才表示清空明细。
        boolean replaceDetails = order instanceof PurchaseOrderWithDetails
                && ((PurchaseOrderWithDetails) order).getOrderDetail() != null;
        List<OrderDetailWithPart> detailParts = replaceDetails
                ? ((PurchaseOrderWithDetails) order).getOrderDetail()
                : null;

        // 合并未传入的订单字段，避免只修改备注时覆盖原有值。
        if (!StringUtils.hasText(order.getOrderNumber())) {
            order.setOrderNumber(existing.getOrderNumber());
        }
        if (order.getTotalAmount() == null) {
            order.setTotalAmount(existing.getTotalAmount());
        }
        if (order.getStatus() == null) {
            order.setStatus(existing.getStatus());
        }
        if (order.getOrderTime() == null) {
            order.setOrderTime(existing.getOrderTime());
        }
        if (order.getExpectedDeliveryDate() == null) {
            order.setExpectedDeliveryDate(existing.getExpectedDeliveryDate());
        }
        if (order.getActualDeliveryDate() == null) {
            order.setActualDeliveryDate(existing.getActualDeliveryDate());
        }
        if (order.getCreatedBy() == null) {
            order.setCreatedBy(existing.getCreatedBy());
        }
        if (order.getRemark() == null) {
            order.setRemark(existing.getRemark());
        }

        if (replaceDetails) {
            BigDecimal totalAmount = BigDecimal.ZERO;
            for (OrderDetailWithPart detailWithPart : detailParts) {
                if (detailWithPart.getQuantity() != null && detailWithPart.getUnitPrice() != null) {
                    totalAmount = totalAmount.add(detailWithPart.getUnitPrice()
                            .multiply(BigDecimal.valueOf(detailWithPart.getQuantity())));
                }
            }
            order.setTotalAmount(totalAmount);
        }

        order.setId(orderId);
        order.setDeleted(existing.getDeleted());
        order.setCreateTime(existing.getCreateTime());
        order.setUpdateTime(LocalDateTime.now());
        if (baseMapper.updateById(order) <= 0) {
            return false;
        }

        if (replaceDetails) {
            orderDetailMapper.physicalDeleteByOrderId(orderId);
            for (OrderDetailWithPart detailWithPart : detailParts) {
                OrderDetail detail = OrderDetail.builder()
                        .orderId(orderId)
                        .partId(detailWithPart.getPartId())
                        .quantity(detailWithPart.getQuantity())
                        .unitPrice(detailWithPart.getUnitPrice())
                        .remark(detailWithPart.getRemark())
                        .build();
                detail.setDeleted(0);
                detail.setCreateTime(LocalDateTime.now());
                detail.setUpdateTime(LocalDateTime.now());
                orderDetailMapper.insert(detail);
            }
        }
        return true;
    }

    @Override
    public boolean updateOrderStatus(Long id, Integer status) {
        if (id == null || status == null) {
            return false;
        }

        LambdaUpdateWrapper<PurchaseOrder> wrapper = new LambdaUpdateWrapper<>();
        wrapper.set(PurchaseOrder::getStatus, status)
               .eq(PurchaseOrder::getId, id);

        // 如果是已入库状态，更新实际交货日期
        if (status == 4) {
            wrapper.set(PurchaseOrder::getActualDeliveryDate, LocalDate.now());
        }

        return update(wrapper);
    }

    @Override
    public OrderStatistics getOrderStatistics(LocalDate startDate, LocalDate endDate) {
        LambdaQueryWrapper<PurchaseOrder> wrapper = new LambdaQueryWrapper<>();

        if (startDate != null) {
            wrapper.ge(PurchaseOrder::getOrderTime, startDate.atStartOfDay());
        }

        if (endDate != null) {
            wrapper.le(PurchaseOrder::getOrderTime, endDate.plusDays(1).atStartOfDay());
        }

        List<PurchaseOrder> orders = baseMapper.selectList(wrapper);

        long totalOrders = orders.size();
        long totalAmount = orders.stream()
                .map(order -> order.getTotalAmount() != null ? order.getTotalAmount() : BigDecimal.ZERO)
                .reduce(BigDecimal.ZERO, BigDecimal::add)
                .longValue();
        long completedOrders = orders.stream()
                .filter(order -> order.getStatus() != null && order.getStatus() == 4)
                .count();
        long pendingOrders = orders.stream()
                .filter(order -> order.getStatus() != null && (order.getStatus() == 1 || order.getStatus() == 2 || order.getStatus() == 3))
                .count();

        return new OrderStatistics() {
            @Override
            public long getTotalOrders() {
                return totalOrders;
            }

            @Override
            public long getTotalAmount() {
                return totalAmount;
            }

            @Override
            public long getCompletedOrders() {
                return completedOrders;
            }

            @Override
            public long getPendingOrders() {
                return pendingOrders;
            }
        };
    }

    @Override
    public List<OrderDetailWithPartAndSupplier> searchOrderDetails(String partName, LocalDateTime startDate, LocalDateTime endDate) {
        // 1. 先根据时间范围查出所有订单ID
        LambdaQueryWrapper<PurchaseOrder> orderWrapper = new LambdaQueryWrapper<>();
        if (startDate != null) {
            orderWrapper.ge(PurchaseOrder::getOrderTime, startDate);
        }
        if (endDate != null) {
            orderWrapper.le(PurchaseOrder::getOrderTime, endDate);
        }
        List<PurchaseOrder> orders = baseMapper.selectList(orderWrapper);
        if (orders == null || orders.isEmpty()) {
            return new ArrayList<>();
        }
        List<Long> orderIds = orders.stream().map(PurchaseOrder::getId).collect(Collectors.toList());

        // 2. 查询所有订单的明细
        LambdaQueryWrapper<OrderDetail> detailWrapper = new LambdaQueryWrapper<>();
        detailWrapper.in(OrderDetail::getOrderId, orderIds);
        List<OrderDetail> allDetails = orderDetailMapper.selectList(detailWrapper);
        if (allDetails == null || allDetails.isEmpty()) {
            return new ArrayList<>();
        }

        // 3. 收集所有 partId
        List<Long> partIds = allDetails.stream()
                .map(OrderDetail::getPartId)
                .distinct()
                .collect(Collectors.toList());

        // 4. 一次性查出所有涉及的零部件
        LambdaQueryWrapper<Part> partWrapper = new LambdaQueryWrapper<>();
        partWrapper.in(Part::getId, partIds);
        if (StringUtils.hasText(partName)) {
            partWrapper.like(Part::getName, partName);
        }
        List<Part> matchedParts = partMapper.selectList(partWrapper);
        if (matchedParts == null || matchedParts.isEmpty()) {
            return new ArrayList<>();
        }
        Map<Long, Part> partMap = matchedParts.stream()
                .collect(Collectors.toMap(Part::getId, p -> p));

        // 5. 只保留被 partName 过滤命中的明细
        List<OrderDetail> filteredDetails = allDetails.stream()
                .filter(d -> partMap.containsKey(d.getPartId()))
                .collect(Collectors.toList());

        // 6. 收集涉及的供应商ID
        List<Long> supplierIds = matchedParts.stream()
                .map(Part::getSupplierId)
                .filter(sid -> sid != null)
                .distinct()
                .collect(Collectors.toList());

        // 7. 一次性查出所有涉及的供应商
        Map<Long, Supplier> supplierMap = Map.of();
        if (!supplierIds.isEmpty()) {
            LambdaQueryWrapper<Supplier> supplierWrapper = new LambdaQueryWrapper<>();
            supplierWrapper.in(Supplier::getId, supplierIds);
            List<Supplier> suppliers = supplierMapper.selectList(supplierWrapper);
            supplierMap = suppliers.stream().collect(Collectors.toMap(Supplier::getId, s -> s));
        }

        // 8. 构建嵌套返回结果
        List<OrderDetailWithPartAndSupplier> result = new ArrayList<>();
        for (OrderDetail detail : filteredDetails) {
            Part part = partMap.get(detail.getPartId());

            OrderDetailWithPartAndSupplier detailDTO = new OrderDetailWithPartAndSupplier();
            detailDTO.setId(detail.getId());
            detailDTO.setOrderId(detail.getOrderId());
            detailDTO.setPartId(detail.getPartId());
            detailDTO.setQuantity(detail.getQuantity());
            detailDTO.setUnitPrice(detail.getUnitPrice());
            detailDTO.setSubtotal(detail.getSubtotal());
            detailDTO.setRemark(detail.getRemark());
            detailDTO.setCreateTime(detail.getCreateTime());
            detailDTO.setUpdateTime(detail.getUpdateTime());

            // 零部件信息
            PartWithSupplier partDTO = new PartWithSupplier();
            partDTO.setId(part.getId());
            partDTO.setPartCode(part.getPartCode());
            partDTO.setName(part.getName());
            partDTO.setModel(part.getModel());
            partDTO.setSpecification(part.getSpecification());
            partDTO.setUnit(part.getUnit());
            partDTO.setPurchasePrice(part.getPurchasePrice());
            partDTO.setSuggestedRetailPrice(part.getSuggestedRetailPrice());
            partDTO.setStockWarningValue(part.getStockWarningValue());
            partDTO.setSupplierId(part.getSupplierId());
            partDTO.setCategory(part.getCategory());
            partDTO.setDescription(part.getDescription());
            partDTO.setCreateTime(part.getCreateTime());
            partDTO.setUpdateTime(part.getUpdateTime());

            // 供应商信息
            if (part.getSupplierId() != null && supplierMap.containsKey(part.getSupplierId())) {
                Supplier supplier = supplierMap.get(part.getSupplierId());
                PartWithSupplier.SupplierInfo supplierInfo = new PartWithSupplier.SupplierInfo();
                supplierInfo.setId(supplier.getId());
                supplierInfo.setSupplierCode(supplier.getSupplierCode());
                supplierInfo.setName(supplier.getName());
                supplierInfo.setContactPerson(supplier.getContactPerson());
                supplierInfo.setPhone(supplier.getPhone());
                supplierInfo.setEmail(supplier.getEmail());
                supplierInfo.setAddress(supplier.getAddress());
                supplierInfo.setCreditRating(supplier.getCreditRating());
                supplierInfo.setStatus(supplier.getStatus());
                partDTO.setSupplier(supplierInfo);
            }

            detailDTO.setPartDetail(partDTO);
            result.add(detailDTO);
        }

        return result;
    }
}
