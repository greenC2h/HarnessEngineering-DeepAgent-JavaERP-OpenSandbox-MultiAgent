package com.motorparts.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.motorparts.common.PageResult;
import com.motorparts.common.Result;
import com.motorparts.common.enums.ResultCode;
import com.motorparts.entity.Part;
import com.motorparts.service.PartService;
import io.swagger.v3.oas.annotations.tags.Tag;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import jakarta.validation.Valid;
import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.List;

/**
 * 产品/零部件管理控制器
 */
@Tag(name = "产品/零部件管理")
@RestController
@RequestMapping("/api/parts")
@RequiredArgsConstructor
@Validated
public class PartController {

    private final PartService partService;

    /**
     * 创建零部件
     */
    @Operation(summary = "创建零部件")
    @PostMapping("/create")
    public Result<Part> create(@Valid @RequestBody Part part) {
        // 检查零件编码是否已存在
        if (partService.existsPartCode(part.getPartCode(), null)) {
            return Result.error(ResultCode.DATA_EXISTS);
        }
        // 手动设置deleted、createTime、updateTime字段
        part.setDeleted(0);
        part.setCreateTime(LocalDateTime.now());
        part.setUpdateTime(LocalDateTime.now());
        boolean success = partService.save(part);
        if (!success) {
            return Result.error();
        }
        return Result.success(part);
    }

    /**
     * 更新零部件
     */
    @Operation(summary = "更新零部件")
    @PutMapping("/update/{id}")
    public Result<Part> update(
            @Parameter(description = "零部件ID") @PathVariable Long id,
            @Valid @RequestBody Part part) {
        part.setId(id);
        // 检查零件编码是否已存在
        if (partService.existsPartCode(part.getPartCode(), id)) {
            return Result.error(ResultCode.DATA_EXISTS);
        }
        // 手动设置updateTime字段
        part.setUpdateTime(LocalDateTime.now());
        boolean success = partService.updateById(part);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success(part);
    }

    /**
     * 删除零部件（逻辑删除）
     */
    @Operation(summary = "删除零部件")
    @DeleteMapping("/delete/{id}")
    public Result<Void> delete(@Parameter(description = "零部件ID") @PathVariable Long id) {
        boolean success = partService.removeById(id);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success();
    }

    /**
     * 获取单个零部件
     */
    @Operation(summary = "获取单个零部件")
    @GetMapping("/get/{id}")
    public Result<Part> getById(@Parameter(description = "零部件ID") @PathVariable Long id) {
        Part part = partService.getById(id);
        if (part == null) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success(part);
    }

    /**
     * 分页查询零部件
     */
    @Operation(summary = "分页查询零部件")
    @GetMapping("/page")
    public Result<PageResult<Part>> page(
            @Parameter(description = "当前页码") @RequestParam(defaultValue = "1") Long current,
            @Parameter(description = "每页大小") @RequestParam(defaultValue = "10") Long size,
            @Parameter(description = "零件名称") @RequestParam(required = false) String name,
            @Parameter(description = "分类") @RequestParam(required = false) String category,
            @Parameter(description = "供应商ID") @RequestParam(required = false) Long supplierId) {
        Page<Part> page = new Page<>(current, size);
        Page<Part> result = partService.pageParts(page, name, category, supplierId);
        return Result.success(PageResult.from(result));
    }

    /**
     * 搜索零部件
     */
    @Operation(summary = "搜索零部件")
    @GetMapping("/search")
    public Result<List<Part>> search(
            @Parameter(description = "零件名称关键字") @RequestParam String name) {
        List<Part> list = partService.searchByName(name);
        return Result.success(list);
    }

    /**
     * 更新采购单价
     */
    @Operation(summary = "更新采购单价")
    @PatchMapping("/update-price/{id}")
    public Result<Void> updatePrice(
            @Parameter(description = "零部件ID") @PathVariable Long id,
            @Parameter(description = "新采购单价") @RequestParam BigDecimal purchasePrice) {
        boolean success = partService.updatePurchasePrice(id, purchasePrice);
        if (!success) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success();
    }

    /**
     * 获取供应商的产品列表
     */
    @Operation(summary = "获取供应商的产品列表")
    @GetMapping("/supplier/{supplierId}")
    public Result<List<Part>> getBySupplierId(
            @Parameter(description = "供应商ID") @PathVariable Long supplierId) {
        List<Part> list = partService.getPartsBySupplierId(supplierId);
        return Result.success(list);
    }
}