package com.motorparts.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.motorparts.common.PageResult;
import com.motorparts.common.Result;
import com.motorparts.common.enums.ResultCode;
import com.motorparts.dto.InventoryWithPart;
import com.motorparts.entity.Inventory;
import com.motorparts.service.InventoryService;
import io.swagger.v3.oas.annotations.tags.Tag;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import lombok.RequiredArgsConstructor;
import org.springframework.validation.annotation.Validated;
import org.springframework.web.bind.annotation.*;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 库存管理控制器
 */
@Tag(name = "库存管理")
@RestController
@RequestMapping("/api/inventory")
@RequiredArgsConstructor
@Validated
public class InventoryController {

    private final InventoryService inventoryService;

    /**
     * 获取单个库存记录
     */
    @Operation(summary = "获取库存记录")
    @GetMapping("/get/{id}")
    public Result<InventoryWithPart> getById(@Parameter(description = "库存ID") @PathVariable Long id) {
        InventoryWithPart inventory = inventoryService.getInventoryWithPart(id);
        if (inventory == null) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }
        return Result.success(inventory);
    }

    /**
     * 分页查询库存
     */
    @Operation(summary = "分页查询库存")
    @GetMapping("/page")
    public Result<PageResult<InventoryWithPart>> page(
            @Parameter(description = "当前页码") @RequestParam(defaultValue = "1") Long current,
            @Parameter(description = "每页大小") @RequestParam(defaultValue = "10") Long size,
            @Parameter(description = "零件名称") @RequestParam(required = false) String partName,
            @Parameter(description = "仓库位置") @RequestParam(required = false) String warehouseLocation) {
        Page<Inventory> page = new Page<>(current, size);
        Page<InventoryWithPart> result = inventoryService.pageInventoriesWithPart(page, partName, warehouseLocation);
        return Result.success(PageResult.from(result));
    }

    /**
     * 入库操作
     */
    @Operation(summary = "入库操作")
    @PostMapping("/inbound")
    public Result<Void> inbound(
            @Parameter(description = "零件ID") @RequestParam Long partId,
            @Parameter(description = "入库数量") @RequestParam Integer quantity,
            @Parameter(description = "仓库位置") @RequestParam(required = false) String warehouseLocation) {
        boolean success = inventoryService.inbound(partId, quantity, warehouseLocation);
        if (!success) {
            return Result.error();
        }
        return Result.success();
    }

    /**
     * 出库操作
     */
    @Operation(summary = "出库操作")
    @PostMapping("/outbound")
    public Result<Void> outbound(
            @Parameter(description = "零件ID") @RequestParam Long partId,
            @Parameter(description = "出库数量") @RequestParam Integer quantity) {
        boolean success = inventoryService.outbound(partId, quantity);
        if (!success) {
            return Result.error(ResultCode.INSUFFICIENT_INVENTORY);
        }
        return Result.success();
    }

    /**
     * 获取库存预警列表
     */
    @Operation(summary = "获取库存预警列表")
    @GetMapping("/warning")
    public Result<List<InventoryWithPart>> getWarningList() {
        List<InventoryWithPart> list = inventoryService.getWarningListWithPart();
        return Result.success(list);
    }

    /**
     * 更新安全库存
     */
    @Operation(summary = "更新安全库存")
    @PatchMapping("/update-safety-stock/{id}")
    public Result<Void> updateSafetyStock(
            @Parameter(description = "库存ID") @PathVariable Long id,
            @Parameter(description = "安全库存量") @RequestParam Integer safetyStock) {
        // 先获取库存记录
        Inventory inventory = inventoryService.getById(id);
        if (inventory == null) {
            return Result.error(ResultCode.DATA_NOT_EXISTS);
        }

        boolean success = inventoryService.updateSafetyStock(inventory.getPartId(), safetyStock);
        if (!success) {
            return Result.error();
        }
        return Result.success();
    }

    /**
     * 库存盘点
     */
    @Operation(summary = "库存盘点")
    @GetMapping("/check")
    public Result<Map<String, Object>> checkInventory() {
        // 获取所有库存记录
        List<Inventory> allInventory = inventoryService.list();

        // 统计各类状态
        long totalItems = allInventory.size();
        long warningItems = allInventory.stream()
                .filter(inv -> inv.getCurrentQuantity() != null && inv.getSafetyStock() != null
                        && inv.getCurrentQuantity() <= inv.getSafetyStock())
                .count();
        long normalItems = totalItems - warningItems;

        // 转换为带零部件信息的列表
        List<InventoryWithPart> inventoryWithParts = new ArrayList<>();
        for (Inventory inv : allInventory) {
            InventoryWithPart iwp = inventoryService.getInventoryWithPart(inv.getId());
            if (iwp != null) {
                inventoryWithParts.add(iwp);
            }
        }

        Map<String, Object> result = new HashMap<>();
        result.put("totalItems", totalItems);
        result.put("warningItems", warningItems);
        result.put("normalItems", normalItems);
        result.put("inventoryList", inventoryWithParts);

        return Result.success(result);
    }
}