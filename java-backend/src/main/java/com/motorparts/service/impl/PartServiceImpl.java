package com.motorparts.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.motorparts.entity.Part;
import com.motorparts.mapper.PartMapper;
import com.motorparts.service.PartService;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.util.List;

/**
 * 产品/零部件服务实现类
 */
@Service
public class PartServiceImpl extends ServiceImpl<PartMapper, Part> implements PartService {

    @Override
    public Page<Part> pageParts(Page<Part> page, String name, String category, Long supplierId) {
        LambdaQueryWrapper<Part> wrapper = new LambdaQueryWrapper<>();

        if (StringUtils.hasText(name)) {
            wrapper.like(Part::getName, name);
        }

        if (StringUtils.hasText(category)) {
            wrapper.eq(Part::getCategory, category);
        }

        if (supplierId != null) {
            wrapper.eq(Part::getSupplierId, supplierId);
        }

        wrapper.orderByDesc(Part::getCreateTime);

        return baseMapper.selectPage(page, wrapper);
    }

    @Override
    public List<Part> searchByName(String name) {
        LambdaQueryWrapper<Part> wrapper = new LambdaQueryWrapper<>();

        if (StringUtils.hasText(name)) {
            wrapper.like(Part::getName, name);
        }

        wrapper.orderByDesc(Part::getCreateTime);

        return baseMapper.selectList(wrapper);
    }

    @Override
    public boolean updatePurchasePrice(Long id, BigDecimal purchasePrice) {
        if (id == null || purchasePrice == null || purchasePrice.compareTo(BigDecimal.ZERO) < 0) {
            return false;
        }

        LambdaUpdateWrapper<Part> wrapper = new LambdaUpdateWrapper<>();
        wrapper.set(Part::getPurchasePrice, purchasePrice)
               .eq(Part::getId, id);

        return update(wrapper);
    }

    @Override
    public List<Part> getPartsBySupplierId(Long supplierId) {
        if (supplierId == null) {
            return List.of();
        }

        LambdaQueryWrapper<Part> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Part::getSupplierId, supplierId)
               .orderByDesc(Part::getCreateTime);

        return baseMapper.selectList(wrapper);
    }

    @Override
    public boolean existsPartCode(String partCode, Long excludeId) {
        LambdaQueryWrapper<Part> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(Part::getPartCode, partCode);

        if (excludeId != null) {
            wrapper.ne(Part::getId, excludeId);
        }

        return baseMapper.selectCount(wrapper) > 0;
    }
}