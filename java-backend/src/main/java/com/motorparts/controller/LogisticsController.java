package com.motorparts.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.motorparts.common.PageResult;
import com.motorparts.common.Result;
import com.motorparts.common.enums.ResultCode;
import com.motorparts.entity.Logistics;
import com.motorparts.service.LogisticsService;
import io.swagger.v3.oas.annotations.tags.Tag;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import lombok.RequiredArgsConstructor;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 物流信息控制器
 */
@Tag(name = "物流管理")
@RestController
@RequestMapping("/api/logistics")
@RequiredArgsConstructor
@Validated
public class LogisticsController {

    private final LogisticsService logisticsService;

    /**
     * 创建物流记录
     */
    @Operation(summary = "创建物流记录")
    @PostMapping("/create")
    public Result<Logistics> create(@Validated @RequestBody Logistics logistics) {
        boolean success = logisticsService.save(logistics);
        if (!success) {
            return Result.error();
        }
        return Result.success(logistics);
    }

    /**
     * 更新物流信息
     */
    @Operation(summary = "更新物流信息")
    @PutMapping("/update/{id}")
    public Result<Logistics> update(
            @Parameter(description = "物流ID") @PathVariable Long id,
            @Validated @RequestBody Logistics logistics) {
        logistics.setId(id);
        boolean success = logisticsService.updateById(logistics);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success(logistics);
    }

    /**
     * 删除物流记录（逻辑删除）
     */
    @Operation(summary = "删除物流记录")
    @DeleteMapping("/delete/{id}")
    public Result<Void> delete(@Parameter(description = "物流ID") @PathVariable Long id) {
        boolean success = logisticsService.removeById(id);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success();
    }

    /**
     * 获取单个物流记录
     */
    @Operation(summary = "获取物流记录")
    @GetMapping("/get/{id}")
    public Result<Logistics> getById(@Parameter(description = "物流ID") @PathVariable Long id) {
        Logistics logistics = logisticsService.getById(id);
        if (logistics == null) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success(logistics);
    }

    /**
     * 分页查询物流信息
     */
    @Operation(summary = "分页查询物流信息")
    @GetMapping("/page")
    public Result<PageResult<Logistics>> page(
            @Parameter(description = "当前页码") @RequestParam(defaultValue = "1") Long current,
            @Parameter(description = "每页大小") @RequestParam(defaultValue = "10") Long size,
            @Parameter(description = "订单ID") @RequestParam(required = false) Long orderId,
            @Parameter(description = "运单号") @RequestParam(required = false) String trackingNumber,
            @Parameter(description = "物流状态") @RequestParam(required = false) Integer status) {
        Page<Logistics> page = new Page<>(current, size);
        Page<Logistics> result = logisticsService.pageLogistics(page, orderId, trackingNumber, status);
        return Result.success(PageResult.from(result));
    }

    /**
     * 根据订单ID获取物流信息
     */
    @Operation(summary = "根据订单获取物流信息")
    @GetMapping("/order/{orderId}")
    public Result<List<Logistics>> getByOrderId(@Parameter(description = "订单ID") @PathVariable Long orderId) {
        List<Logistics> list = logisticsService.getLogisticsByOrderId(orderId);
        return Result.success(list);
    }

    /**
     * 更新物流状态
     */
    @Operation(summary = "更新物流状态")
    @PatchMapping("/update-status/{id}")
    public Result<Void> updateStatus(
            @Parameter(description = "物流ID") @PathVariable Long id,
            @Parameter(description = "新状态") @RequestParam Integer status) {
        boolean success = logisticsService.updateStatus(id, status);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success();
    }

    /**
     * 更新发货信息
     */
    @Operation(summary = "更新发货信息")
    @PatchMapping("/update-shipping/{id}")
    public Result<Void> updateShipping(
            @Parameter(description = "物流ID") @PathVariable Long id,
            @Parameter(description = "发货时间") @RequestParam @DateTimeFormat(pattern = "yyyy-MM-dd HH:mm:ss") LocalDateTime shipTime,
            @Parameter(description = "运单号") @RequestParam String trackingNumber,
            @Parameter(description = "物流公司") @RequestParam(required = false) String logisticsCompany) {
        boolean success = logisticsService.updateShippingInfo(id, shipTime, trackingNumber, logisticsCompany);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success();
    }

    /**
     * 更新收货信息
     */
    @Operation(summary = "更新收货信息")
    @PatchMapping("/update-receiving/{id}")
    public Result<Void> updateReceiving(
            @Parameter(description = "物流ID") @PathVariable Long id,
            @Parameter(description = "实际到达时间") @RequestParam @DateTimeFormat(pattern = "yyyy-MM-dd HH:mm:ss") LocalDateTime actualArrivalTime,
            @Parameter(description = "收货人") @RequestParam String receiver) {
        boolean success = logisticsService.updateReceivingInfo(id, actualArrivalTime, receiver);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success();
    }
}