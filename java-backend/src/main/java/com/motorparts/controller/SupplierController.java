package com.motorparts.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.motorparts.common.PageResult;
import com.motorparts.common.Result;
import com.motorparts.common.enums.ResultCode;
import com.motorparts.entity.Supplier;
import com.motorparts.service.SupplierService;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.tags.Tag;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import jakarta.validation.Valid;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 供应商管理控制器
 */
@Tag(name = "供应商管理")
@RestController
@RequestMapping("/api/suppliers")
@RequiredArgsConstructor
@Validated
public class SupplierController {

    private final SupplierService supplierService;

    /**
     * 创建供应商
     */
    @Operation(summary = "创建供应商")
    @PostMapping("/create")
    public Result<Supplier> create(@Valid @RequestBody Supplier supplier) {
        // 手动设置deleted、createTime、updateTime字段
        supplier.setDeleted(0);
        supplier.setCreateTime(LocalDateTime.now());
        supplier.setUpdateTime(LocalDateTime.now());
        boolean success = supplierService.save(supplier);
        if (!success) {
            return Result.error(ResultCode.DATA_EXISTS);
        }
        return Result.success(supplier);
    }

    /**
     * 更新供应商
     */
    @Operation(summary = "更新供应商")
    @PutMapping("/update/{id}")
    public Result<Supplier> update(
            @Parameter(description = "供应商ID") @PathVariable Long id,
            @Valid @RequestBody Supplier supplier) {
        supplier.setId(id);
        // 手动设置updateTime字段
        supplier.setUpdateTime(LocalDateTime.now());
        boolean success = supplierService.updateById(supplier);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success(supplier);
    }

    /**
     * 删除供应商（逻辑删除）
     */
    @Operation(summary = "删除供应商")
    @DeleteMapping("/delete/{id}")
    public Result<Void> delete(@Parameter(description = "供应商ID") @PathVariable Long id) {
        boolean success = supplierService.removeById(id);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success();
    }

    /**
     * 获取单个供应商
     */
    @Operation(summary = "获取单个供应商")
    @GetMapping("/get/{id}")
    public Result<Supplier> getById(@Parameter(description = "供应商ID") @PathVariable Long id) {
        Supplier supplier = supplierService.getById(id);
        if (supplier == null) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success(supplier);
    }

    /**
     * 分页查询供应商
     */
    @Operation(summary = "分页查询供应商")
    @GetMapping("/page")
    public Result<PageResult<Supplier>> page(
            @Parameter(description = "当前页码") @RequestParam(defaultValue = "1") Long current,
            @Parameter(description = "每页大小") @RequestParam(defaultValue = "10") Long size,
            @Parameter(description = "供应商名称") @RequestParam(required = false) String name,
            @Parameter(description = "合作状态") @RequestParam(required = false) Integer status,
            @Parameter(description = "信用评级") @RequestParam(required = false) String creditRating) {
        Page<Supplier> page = new Page<>(current, size);
        Page<Supplier> result = supplierService.pageSuppliers(page, name, status, creditRating);
        return Result.success(PageResult.from(result));
    }

    /**
     * 搜索供应商
     */
    @Operation(summary = "搜索供应商")
    @GetMapping("/search")
    public Result<List<Supplier>> search(
            @Parameter(description = "供应商名称关键字") @RequestParam String name) {
        List<Supplier> list = supplierService.searchByName(name);
        return Result.success(list);
    }

    /**
     * 更新供应商状态
     */
    @Operation(summary = "更新供应商状态")
    @PatchMapping("/update-status/{id}")
    public Result<Void> updateStatus(
            @Parameter(description = "供应商ID") @PathVariable Long id,
            @Parameter(description = "新状态") @RequestParam Integer status) {
        boolean success = supplierService.updateStatus(id, status);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success();
    }

    /**
     * 更新信用评级
     */
    @Operation(summary = "更新信用评级")
    @PatchMapping("/update-credit-rating/{id}")
    public Result<Void> updateCreditRating(
            @Parameter(description = "供应商ID") @PathVariable Long id,
            @Parameter(description = "新信用评级") @RequestParam String creditRating) {
        boolean success = supplierService.updateCreditRating(id, creditRating);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success();
    }
}