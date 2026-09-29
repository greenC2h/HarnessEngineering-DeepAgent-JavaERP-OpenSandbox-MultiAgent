package com.motorparts.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.IService;
import com.motorparts.entity.Customer;

import java.util.List;

/**
 * 客户服务接口
 */
public interface CustomerService extends IService<Customer> {

    /**
     * 分页查询客户
     *
     * @param page     分页参数
     * @param name     客户名称（可选）
     * @param customerType 客户类型（可选）
     * @param discountLevel 折扣等级（可选）
     * @return 分页结果
     */
    Page<Customer> pageCustomers(Page<Customer> page, String name, Integer customerType, Integer discountLevel);

    /**
     * 根据名称搜索客户
     *
     * @param name 客户名称关键字
     * @return 客户列表
     */
    List<Customer> searchByName(String name);

    /**
     * 更新客户类型
     *
     * @param id           客户ID
     * @param customerType 新客户类型
     * @return 是否成功
     */
    boolean updateCustomerType(Long id, Integer customerType);

    /**
     * 更新折扣等级
     *
     * @param id           客户ID
     * @param discountLevel 新折扣等级
     * @return 是否成功
     */
    boolean updateDiscountLevel(Long id, Integer discountLevel);
}