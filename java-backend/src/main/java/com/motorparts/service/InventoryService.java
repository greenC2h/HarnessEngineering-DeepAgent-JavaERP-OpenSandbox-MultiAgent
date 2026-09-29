package com.motorparts.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.IService;
import com.motorparts.dto.InventoryWithPart;
import com.motorparts.entity.Inventory;

import java.util.List;

/**
 * 库存服务接口
 */
public interface InventoryService extends IService<Inventory> {

    /**
     * 分页查询库存
     *
     * @param page     分页参数
     * @param partName 零件名称（可选）
     * @param warehouseLocation 仓库位置（可选）
     * @return 分页结果
     */
    Page<Inventory> pageInventories(Page<Inventory> page, String partName, String warehouseLocation);

    /**
     * 入库操作
     *
     * @param partId   零件ID
     * @param quantity 入库数量
     * @param warehouseLocation 仓库位置
     * @return 是否成功
     */
    boolean inbound(Long partId, Integer quantity, String warehouseLocation);

    /**
     * 出库操作
     *
     * @param partId   零件ID
     * @param quantity 出库数量
     * @return 是否成功
     */
    boolean outbound(Long partId, Integer quantity);

    /**
     * 获取库存预警列表
     *
     * @return 库存预警列表
     */
    List<Inventory> getWarningList();

    /**
     * 更新安全库存
     *
     * @param partId      零件ID
     * @param safetyStock 安全库存量
     * @return 是否成功
     */
    boolean updateSafetyStock(Long partId, Integer safetyStock);

    /**
     * 获取单个库存记录（含零部件信息）
     *
     * @param id 库存ID
     * @return 库存及零部件信息
     */
    InventoryWithPart getInventoryWithPart(Long id);

    /**
     * 分页查询库存（含零部件信息）
     *
     * @param page              分页参数
     * @param partName          零件名称（可选）
     * @param warehouseLocation 仓库位置（可选）
     * @return 分页结果
     */
    Page<InventoryWithPart> pageInventoriesWithPart(Page<Inventory> page, String partName, String warehouseLocation);

    /**
     * 获取库存预警列表（含零部件信息）
     *
     * @return 库存预警列表
     */
    List<InventoryWithPart> getWarningListWithPart();
}