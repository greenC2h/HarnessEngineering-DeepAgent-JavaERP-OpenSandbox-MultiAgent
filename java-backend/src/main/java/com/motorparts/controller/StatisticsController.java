package com.motorparts.controller;

import com.motorparts.common.Result;
import com.motorparts.entity.*;
import com.motorparts.mapper.*;
import com.motorparts.service.PurchaseOrderService;
import io.swagger.v3.oas.annotations.tags.Tag;
import io.swagger.v3.oas.annotations.Operation;
import lombok.RequiredArgsConstructor;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.web.bind.annotation.*;

import java.time.LocalDate;
import java.util.*;
import java.util.stream.Collectors;

/**
 * 统计分析控制器
 */
@Tag(name = "统计分析")
@RestController
@RequestMapping("/api/statistics")
public class StatisticsController {

    private final PurchaseOrderService purchaseOrderService;
    private final SupplierMapper supplierMapper;
    private final PartMapper partMapper;
    private final CustomerMapper customerMapper;
    private final UserMapper userMapper;
    private final InventoryMapper inventoryMapper;

    public StatisticsController(PurchaseOrderService purchaseOrderService, SupplierMapper supplierMapper, PartMapper partMapper, CustomerMapper customerMapper, UserMapper userMapper, InventoryMapper inventoryMapper) {
        this.purchaseOrderService = purchaseOrderService;
        this.supplierMapper = supplierMapper;
        this.partMapper = partMapper;
        this.customerMapper = customerMapper;
        this.userMapper = userMapper;
        this.inventoryMapper = inventoryMapper;
    }

    /**
     * 获取仪表盘统计数据
     */
    @Operation(summary = "获取仪表盘统计数据")
    @GetMapping("/dashboard")
    public Result<Map<String, Object>> getDashboard() {
        Map<String, Object> dashboard = new HashMap<>();

        // 供应商总数
        long supplierCount = supplierMapper.selectCount(null);
        dashboard.put("supplierCount", supplierCount);

        // 产品总数
        long partCount = partMapper.selectCount(null);
        dashboard.put("partCount", partCount);

        // 客户总数
        long customerCount = customerMapper.selectCount(null);
        dashboard.put("customerCount", customerCount);

        // 用户总数
        long userCount = userMapper.selectCount(null);
        dashboard.put("userCount", userCount);

        // 库存记录数
        long inventoryCount = inventoryMapper.selectCount(null);
        dashboard.put("inventoryCount", inventoryCount);

        // 本月采购统计
        LocalDate now = LocalDate.now();
        LocalDate monthStart = now.withDayOfMonth(1);
        PurchaseOrderService.OrderStatistics monthStats = purchaseOrderService.getOrderStatistics(monthStart, now);
        Map<String, Object> monthPurchase = new HashMap<>();
        monthPurchase.put("orderCount", monthStats.getTotalOrders());
        monthPurchase.put("totalAmount", monthStats.getTotalAmount());
        monthPurchase.put("completedCount", monthStats.getCompletedOrders());
        dashboard.put("monthPurchase", monthPurchase);

        return Result.success(dashboard);
    }

    /**
     * 获取供应商统计
     */
    @Operation(summary = "获取供应商统计")
    @GetMapping("/suppliers")
    public Result<Map<String, Object>> getSupplierStatistics() {
        List<Supplier> suppliers = supplierMapper.selectList(null);

        Map<String, Object> stats = new HashMap<>();

        // 按状态分组
        Map<Integer, Long> byStatus = suppliers.stream()
                .collect(Collectors.groupingBy(
                        s -> s.getStatus() != null ? s.getStatus() : 0,
                        Collectors.counting()
                ));
        stats.put("byStatus", byStatus);

        // 按信用评级分组
        Map<String, Long> byCreditRating = suppliers.stream()
                .filter(s -> s.getCreditRating() != null)
                .collect(Collectors.groupingBy(
                        Supplier::getCreditRating,
                        Collectors.counting()
                ));
        stats.put("byCreditRating", byCreditRating);

        stats.put("total", suppliers.size());

        return Result.success(stats);
    }

    /**
     * 获取产品分类统计
     */
    @Operation(summary = "获取产品分类统计")
    @GetMapping("/parts")
    public Result<Map<String, Object>> getPartStatistics() {
        List<Part> parts = partMapper.selectList(null);

        Map<String, Object> stats = new HashMap<>();

        // 按分类分组
        Map<String, Long> byCategory = parts.stream()
                .filter(p -> p.getCategory() != null)
                .collect(Collectors.groupingBy(
                        Part::getCategory,
                        Collectors.counting()
                ));
        stats.put("byCategory", byCategory);

        // 价格区间分布
        Map<String, Long> priceRanges = new HashMap<>();
        priceRanges.put("0-100", parts.stream().filter(p -> p.getPurchasePrice() != null && p.getPurchasePrice().doubleValue() < 100).count());
        priceRanges.put("100-500", parts.stream().filter(p -> p.getPurchasePrice() != null && p.getPurchasePrice().doubleValue() >= 100 && p.getPurchasePrice().doubleValue() < 500).count());
        priceRanges.put("500-1000", parts.stream().filter(p -> p.getPurchasePrice() != null && p.getPurchasePrice().doubleValue() >= 500 && p.getPurchasePrice().doubleValue() < 1000).count());
        priceRanges.put("1000+", parts.stream().filter(p -> p.getPurchasePrice() != null && p.getPurchasePrice().doubleValue() >= 1000).count());
        stats.put("priceRanges", priceRanges);

        stats.put("total", parts.size());

        return Result.success(stats);
    }

    /**
     * 获取库存预警统计
     */
    @Operation(summary = "获取库存预警统计")
    @GetMapping("/inventory")
    public Result<Map<String, Object>> getInventoryStatistics() {
        List<Inventory> inventories = inventoryMapper.selectList(null);

        Map<String, Object> stats = new HashMap<>();

        // 库存状态分布
        long warningCount = inventories.stream()
                .filter(inv -> inv.getCurrentQuantity() <= inv.getSafetyStock())
                .count();
        long normalCount = inventories.size() - warningCount;

        Map<String, Long> statusDistribution = new HashMap<>();
        statusDistribution.put("warning", warningCount);
        statusDistribution.put("normal", normalCount);
        stats.put("statusDistribution", statusDistribution);

        // 库存为0的产品
        long zeroStock = inventories.stream()
                .filter(inv -> inv.getCurrentQuantity() == 0)
                .count();
        stats.put("zeroStockCount", zeroStock);

        stats.put("total", inventories.size());

        return Result.success(stats);
    }

    /**
     * 获取月度采购趋势
     */
    @Operation(summary = "获取月度采购趋势")
    @GetMapping("/monthly-trend")
    public Result<List<Map<String, Object>>> getMonthlyTrend(
            @RequestParam(required = false) @DateTimeFormat(pattern = "yyyy-MM-dd") LocalDate startDateParam,
            @RequestParam(required = false) @DateTimeFormat(pattern = "yyyy-MM-dd") LocalDate endDateParam) {
        // 默认查询最近6个月
        LocalDate startDate = startDateParam != null ? startDateParam : LocalDate.now().minusMonths(6).withDayOfMonth(1);
        LocalDate endDate = endDateParam != null ? endDateParam : LocalDate.now();

        // 获取所有订单
        List<PurchaseOrder> orders = purchaseOrderService.list();

        // 按月份分组统计
        Map<String, List<PurchaseOrder>> byMonth = orders.stream()
                .filter(o -> o.getOrderTime() != null)
                .filter(o -> {
                    LocalDate orderDate = o.getOrderTime().toLocalDate();
                    return !orderDate.isBefore(startDate) && !orderDate.isAfter(endDate);
                })
                .collect(Collectors.groupingBy(o -> o.getOrderTime().toLocalDate().getYear() + "-" + String.format("%02d", o.getOrderTime().toLocalDate().getMonthValue())));

        List<Map<String, Object>> trend = new ArrayList<>();
        byMonth.forEach((month, monthOrders) -> {
            Map<String, Object> item = new HashMap<>();
            item.put("month", month);
            item.put("orderCount", monthOrders.size());
            item.put("totalAmount", monthOrders.stream()
                    .map(o -> o.getTotalAmount() != null ? o.getTotalAmount() : java.math.BigDecimal.ZERO)
                    .reduce(java.math.BigDecimal.ZERO, java.math.BigDecimal::add));
            trend.add(item);
        });

        // 按月份排序
        trend.sort(Comparator.comparing(m -> (String) m.get("month")));

        return Result.success(trend);
    }
}