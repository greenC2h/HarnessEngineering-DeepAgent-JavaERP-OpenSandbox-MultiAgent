package com.motorparts.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.motorparts.entity.Customer;
import com.motorparts.mapper.CustomerMapper;
import com.motorparts.service.CustomerService;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.List;

/**
 * 客户服务实现类
 */
@Service
public class CustomerServiceImpl extends ServiceImpl<CustomerMapper, Customer> implements CustomerService {

    @Override
    public Page<Customer> pageCustomers(Page<Customer> page, String name, Integer customerType, Integer discountLevel) {
        LambdaQueryWrapper<Customer> wrapper = new LambdaQueryWrapper<>();

        if (StringUtils.hasText(name)) {
            wrapper.like(Customer::getName, name);
        }

        if (customerType != null) {
            wrapper.eq(Customer::getCustomerType, customerType);
        }

        if (discountLevel != null) {
            wrapper.eq(Customer::getDiscountLevel, discountLevel);
        }

        wrapper.orderByDesc(Customer::getCreateTime);

        return baseMapper.selectPage(page, wrapper);
    }

    @Override
    public List<Customer> searchByName(String name) {
        LambdaQueryWrapper<Customer> wrapper = new LambdaQueryWrapper<>();

        if (StringUtils.hasText(name)) {
            wrapper.like(Customer::getName, name);
        }

        wrapper.orderByDesc(Customer::getCreateTime);

        return baseMapper.selectList(wrapper);
    }

    @Override
    public boolean updateCustomerType(Long id, Integer customerType) {
        if (id == null || customerType == null) {
            return false;
        }

        LambdaUpdateWrapper<Customer> wrapper = new LambdaUpdateWrapper<>();
        wrapper.set(Customer::getCustomerType, customerType)
               .eq(Customer::getId, id);

        return update(wrapper);
    }

    @Override
    public boolean updateDiscountLevel(Long id, Integer discountLevel) {
        if (id == null || discountLevel == null) {
            return false;
        }

        LambdaUpdateWrapper<Customer> wrapper = new LambdaUpdateWrapper<>();
        wrapper.set(Customer::getDiscountLevel, discountLevel)
               .eq(Customer::getId, id);

        return update(wrapper);
    }
}