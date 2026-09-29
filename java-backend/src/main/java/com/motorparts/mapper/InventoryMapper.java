package com.motorparts.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.motorparts.entity.Inventory;
import org.apache.ibatis.annotations.Mapper;

/**
 * 库存 Mapper 接口
 */
@Mapper
public interface InventoryMapper extends BaseMapper<Inventory> {

}