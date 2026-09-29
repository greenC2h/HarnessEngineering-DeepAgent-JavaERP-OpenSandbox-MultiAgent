package com.motorparts.controller;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.motorparts.common.PageResult;
import com.motorparts.common.Result;
import com.motorparts.common.enums.ResultCode;
import com.motorparts.dto.OrderDetailWithPartAndSupplier;
import com.motorparts.entity.OrderDetail;
import com.motorparts.entity.OrderDetailWithPart;
import com.motorparts.entity.Part;
import com.motorparts.entity.PurchaseOrder;
import com.motorparts.entity.PurchaseOrderWithDetails;
import com.motorparts.mapper.OrderDetailMapper;
import com.motorparts.mapper.PartMapper;
import com.motorparts.service.PurchaseOrderService;
import io.swagger.v3.oas.annotations.tags.Tag;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import lombok.RequiredArgsConstructor;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import jakarta.validation.Valid;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 采购订单控制器
 */
@Tag(name = "采购订单管理")
@RestController
@RequestMapping("/api/orders")
@RequiredArgsConstructor
@Validated
public class PurchaseOrderController {

    private final PurchaseOrderService purchaseOrderService;
    private final OrderDetailMapper orderDetailMapper;
    private final PartMapper partMapper;

    /**
     * 创建采购订单
     */
    @Operation(summary = "创建采购订单")
    @PostMapping("/create")
    public Result<PurchaseOrderWithDetails> create(@Valid @RequestBody PurchaseOrderWithDetails order) {
        boolean success = purchaseOrderService.createOrder(order);
        if (!success) {
            return Result.error(ResultCode.DATA_EXISTS);
        }
        return Result.success(order);
    }

    /**
     * 更新采购订单
     */
    @Operation(summary = "更新采购订单")
    @PutMapping("/update/{id}")
    public Result<PurchaseOrderWithDetails> update(
            @Parameter(description = "订单ID") @PathVariable Long id,
            @Valid @RequestBody PurchaseOrderWithDetails order) {
        order.setId(id);
        boolean success = purchaseOrderService.updateById(order);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success(buildOrderWithDetails(id));
    }

    /**
     * 删除采购订单（逻辑删除）
     */
    @Operation(summary = "删除采购订单")
    @DeleteMapping("/delete/{id}")
    public Result<Void> delete(@Parameter(description = "订单ID") @PathVariable Long id) {
        boolean success = purchaseOrderService.removeById(id);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success();
    }

    /**
     * 获取单个订单（包含订单明细和零部件详情）
     */
    @Operation(summary = "获取单个订单")
    @GetMapping("/get/{id}")
    public Result<PurchaseOrderWithDetails> getById(@Parameter(description = "订单ID") @PathVariable Long id) {
        PurchaseOrder order = purchaseOrderService.getById(id);
        if (order == null) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }

        return Result.success(buildOrderWithDetails(id));
    }

    private PurchaseOrderWithDetails buildOrderWithDetails(Long id) {
        PurchaseOrder order = purchaseOrderService.getById(id);
        // 构建带详情的订单对象
        PurchaseOrderWithDetails orderWithDetails = new PurchaseOrderWithDetails();
        // 复制订单基本信息
        orderWithDetails.setId(order.getId());
        orderWithDetails.setOrderNumber(order.getOrderNumber());
        orderWithDetails.setTotalAmount(order.getTotalAmount());
        orderWithDetails.setStatus(order.getStatus());
        orderWithDetails.setOrderTime(order.getOrderTime());
        orderWithDetails.setExpectedDeliveryDate(order.getExpectedDeliveryDate());
        orderWithDetails.setActualDeliveryDate(order.getActualDeliveryDate());
        orderWithDetails.setCreatedBy(order.getCreatedBy());
        orderWithDetails.setRemark(order.getRemark());
        orderWithDetails.setDeleted(order.getDeleted());
        orderWithDetails.setCreateTime(order.getCreateTime());
        orderWithDetails.setUpdateTime(order.getUpdateTime());

        // 查询订单明细
        List<OrderDetail> details = orderDetailMapper.selectList(
                new LambdaQueryWrapper<OrderDetail>()
                        .eq(OrderDetail::getOrderId, id)
        );

        // 构建带零部件详情的订单明细列表
        List<OrderDetailWithPart> detailWithParts = new ArrayList<>();
        for (OrderDetail detail : details) {
            OrderDetailWithPart detailWithPart = new OrderDetailWithPart();
            // 复制明细基本信息
            detailWithPart.setId(detail.getId());
            detailWithPart.setOrderId(detail.getOrderId());
            detailWithPart.setPartId(detail.getPartId());
            detailWithPart.setQuantity(detail.getQuantity());
            detailWithPart.setUnitPrice(detail.getUnitPrice());
            detailWithPart.setSubtotal(detail.getSubtotal());
            detailWithPart.setRemark(detail.getRemark());
            detailWithPart.setDeleted(detail.getDeleted());
            detailWithPart.setCreateTime(detail.getCreateTime());
            detailWithPart.setUpdateTime(detail.getUpdateTime());

            // 查询零部件详情
            Part part = partMapper.selectById(detail.getPartId());
            detailWithPart.setPartDetail(part);

            detailWithParts.add(detailWithPart);
        }

        orderWithDetails.setOrderDetail(detailWithParts);
        return orderWithDetails;
    }

    /**
     * 获取订单详情（包含明细）
     */
    @Operation(summary = "获取订单详情")
    @GetMapping("/details/{id}")
    public Result<Map<String, Object>> getOrderDetails(@Parameter(description = "订单ID") @PathVariable Long id) {
        PurchaseOrder order = purchaseOrderService.getById(id);
        if (order == null) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }

        List<OrderDetail> details = orderDetailMapper.selectList(
                new com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper<OrderDetail>()
                        .eq(OrderDetail::getOrderId, id)
        );

        Map<String, Object> result = new HashMap<>();
        result.put("order", order);
        result.put("details", details);
        return Result.success(result);
    }

    /**
     * 分页查询订单（包含订单明细和零部件详情）
     */
    @Operation(summary = "分页查询订单")
    @GetMapping("/page")
    public Result<PageResult<PurchaseOrderWithDetails>> page(
            @Parameter(description = "当前页码") @RequestParam(defaultValue = "1") Long current,
            @Parameter(description = "每页大小") @RequestParam(defaultValue = "10") Long size,
            @Parameter(description = "订单编号") @RequestParam(required = false) String orderNumber,
            @Parameter(description = "订单状态") @RequestParam(required = false) Integer status,
            @Parameter(description = "开始日期") @RequestParam(required = false) @DateTimeFormat(pattern = "yyyy-MM-dd") LocalDate startDate,
            @Parameter(description = "结束日期") @RequestParam(required = false) @DateTimeFormat(pattern = "yyyy-MM-dd") LocalDate endDate) {
        Page<PurchaseOrder> page = new Page<>(current, size);
        Page<PurchaseOrder> result = purchaseOrderService.pageOrders(page, orderNumber, status, startDate, endDate);

        // 将普通订单转换为带详情的订单列表
        List<PurchaseOrderWithDetails> orderWithDetailsList = new ArrayList<>();
        for (PurchaseOrder order : result.getRecords()) {
            PurchaseOrderWithDetails orderWithDetails = new PurchaseOrderWithDetails();
            // 复制订单基本信息
            orderWithDetails.setId(order.getId());
            orderWithDetails.setOrderNumber(order.getOrderNumber());
            orderWithDetails.setTotalAmount(order.getTotalAmount());
            orderWithDetails.setStatus(order.getStatus());
            orderWithDetails.setOrderTime(order.getOrderTime());
            orderWithDetails.setExpectedDeliveryDate(order.getExpectedDeliveryDate());
            orderWithDetails.setActualDeliveryDate(order.getActualDeliveryDate());
            orderWithDetails.setCreatedBy(order.getCreatedBy());
            orderWithDetails.setRemark(order.getRemark());
            orderWithDetails.setDeleted(order.getDeleted());
            orderWithDetails.setCreateTime(order.getCreateTime());
            orderWithDetails.setUpdateTime(order.getUpdateTime());

            // 查询订单明细
            List<OrderDetail> details = orderDetailMapper.selectList(
                    new LambdaQueryWrapper<OrderDetail>()
                            .eq(OrderDetail::getOrderId, order.getId())
            );

            // 构建带零部件详情的订单明细列表
            List<OrderDetailWithPart> detailWithParts = new ArrayList<>();
            for (OrderDetail detail : details) {
                OrderDetailWithPart detailWithPart = new OrderDetailWithPart();
                // 复制明细基本信息
                detailWithPart.setId(detail.getId());
                detailWithPart.setOrderId(detail.getOrderId());
                detailWithPart.setPartId(detail.getPartId());
                detailWithPart.setQuantity(detail.getQuantity());
                detailWithPart.setUnitPrice(detail.getUnitPrice());
                detailWithPart.setSubtotal(detail.getSubtotal());
                detailWithPart.setRemark(detail.getRemark());
                detailWithPart.setDeleted(detail.getDeleted());
                detailWithPart.setCreateTime(detail.getCreateTime());
                detailWithPart.setUpdateTime(detail.getUpdateTime());

                // 查询零部件详情
                Part part = partMapper.selectById(detail.getPartId());
                detailWithPart.setPartDetail(part);

                detailWithParts.add(detailWithPart);
            }

            orderWithDetails.setOrderDetail(detailWithParts);
            orderWithDetailsList.add(orderWithDetails);
        }

        // 构建分页结果
        PageResult<PurchaseOrderWithDetails> pageResult = new PageResult<>();
        pageResult.setTotal(result.getTotal());
        pageResult.setPages(result.getPages());
        pageResult.setCurrent(result.getCurrent());
        pageResult.setSize(result.getSize());
        pageResult.setRecords(orderWithDetailsList);

        return Result.success(pageResult);
    }

    /**
     * 更新订单状态
     */
    @Operation(summary = "更新订单状态")
    @PatchMapping("/update-status/{id}")
    public Result<Void> updateStatus(
            @Parameter(description = "订单ID") @PathVariable Long id,
            @Parameter(description = "新状态") @RequestParam Integer status) {
        boolean success = purchaseOrderService.updateOrderStatus(id, status);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success();
    }

    /**
     * 获取采购统计
     */
    @Operation(summary = "获取采购统计")
    @GetMapping("/statistics")
    public Result<Map<String, Object>> getStatistics(
            @Parameter(description = "开始日期") @RequestParam(required = false) @DateTimeFormat(pattern = "yyyy-MM-dd") LocalDate startDate,
            @Parameter(description = "结束日期") @RequestParam(required = false) @DateTimeFormat(pattern = "yyyy-MM-dd") LocalDate endDate) {
        PurchaseOrderService.OrderStatistics statistics = purchaseOrderService.getOrderStatistics(startDate, endDate);

        Map<String, Object> result = new HashMap<>();
        result.put("totalOrders", statistics.getTotalOrders());
        result.put("totalAmount", statistics.getTotalAmount());
        result.put("completedOrders", statistics.getCompletedOrders());
        result.put("pendingOrders", statistics.getPendingOrders());
        return Result.success(result);
    }

    /**
     * 搜索订单明细（根据零部件名称和时间范围）
     * 时间参数支持两种格式：yyyy-MM-dd（自动补全00:00:00）或 yyyy-MM-dd HH:mm:ss
     */
    @Operation(summary = "搜索订单明细")
    @GetMapping("/search-details")
    public Result<List<OrderDetailWithPartAndSupplier>> searchOrderDetails(
            @Parameter(description = "零部件名称（模糊匹配）") @RequestParam(required = false) String partName,
            @Parameter(description = "开始时间（支持 yyyy-MM-dd 或 yyyy-MM-dd HH:mm:ss）") @RequestParam(required = false) String startDate,
            @Parameter(description = "结束时间（支持 yyyy-MM-dd 或 yyyy-MM-dd HH:mm:ss）") @RequestParam(required = false) String endDate) {
        LocalDateTime startDateTime = parseDateTime(startDate, true);
        LocalDateTime endDateTime = parseDateTime(endDate, false);
        List<OrderDetailWithPartAndSupplier> result = purchaseOrderService.searchOrderDetails(partName, startDateTime, endDateTime);
        return Result.success(result);
    }

    /**
     * 解析时间字符串，支持两种格式：
     * - yyyy-MM-dd（自动补全00:00:00或23:59:59）
     * - yyyy-MM-dd HH:mm:ss（直接使用）
     */
    private LocalDateTime parseDateTime(String dateStr, boolean isStart) {
        if (dateStr == null || dateStr.trim().isEmpty()) {
            return null;
        }
        dateStr = dateStr.trim();
        if (dateStr.length() == 10) {
            // 纯日期格式，补全时间
            DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd");
            java.time.LocalDate date = java.time.LocalDate.parse(dateStr, formatter);
            return isStart ? date.atStartOfDay() : date.atTime(23, 59, 59);
        } else {
            // 日期时间格式
            DateTimeFormatter formatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
            return LocalDateTime.parse(dateStr, formatter);
        }
    }
}
