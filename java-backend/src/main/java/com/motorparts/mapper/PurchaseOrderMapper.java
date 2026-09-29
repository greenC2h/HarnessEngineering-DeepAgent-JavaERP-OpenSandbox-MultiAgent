package com.motorparts.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.motorparts.entity.PurchaseOrder;
import org.apache.ibatis.annotations.Delete;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;

/**
 * 采购订单 Mapper 接口
 */
@Mapper
public interface PurchaseOrderMapper extends BaseMapper<PurchaseOrder> {

    /**
     * 物理删除订单（绕过 @TableLogic 软删除，直接从数据库删除）
     */
    @Delete("DELETE FROM purchase_order WHERE id = #{id}")
    int physicalDeleteById(@Param("id") Long id);
}