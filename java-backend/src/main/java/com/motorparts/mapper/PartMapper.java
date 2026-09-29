package com.motorparts.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.motorparts.entity.Part;
import org.apache.ibatis.annotations.Mapper;

/**
 * 产品/零部件 Mapper 接口
 */
@Mapper
public interface PartMapper extends BaseMapper<Part> {

}