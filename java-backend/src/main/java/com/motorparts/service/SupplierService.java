package com.motorparts.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.IService;
import com.motorparts.entity.Supplier;

import java.util.List;

/**
 * 供应商服务接口
 */
public interface SupplierService extends IService<Supplier> {

    /**
     * 分页查询供应商
     *
     * @param page     分页参数
     * @param name     供应商名称（可选）
     * @param status   合作状态（可选）
     * @param creditRating 信用评级（可选）
     * @return 分页结果
     */
    Page<Supplier> pageSuppliers(Page<Supplier> page, String name, Integer status, String creditRating);

    /**
     * 根据名称搜索供应商
     *
     * @param name 供应商名称关键字
     * @return 供应商列表
     */
    List<Supplier> searchByName(String name);

    /**
     * 更新供应商状态
     *
     * @param id     供应商ID
     * @param status 新状态
     * @return 是否成功
     */
    boolean updateStatus(Long id, Integer status);

    /**
     * 更新信用评级
     *
     * @param id           供应商ID
     * @param creditRating 新信用评级
     * @return 是否成功
     */
    boolean updateCreditRating(Long id, String creditRating);
}