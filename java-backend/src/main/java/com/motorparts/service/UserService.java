package com.motorparts.service;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.IService;
import com.motorparts.entity.User;

import java.util.List;

/**
 * 用户/员工服务接口
 */
public interface UserService extends IService<User> {

    /**
     * 分页查询用户
     *
     * @param page     分页参数
     * @param username 用户名（可选）
     * @param role     角色（可选）
     * @param department 部门（可选）
     * @return 分页结果
     */
    Page<User> pageUsers(Page<User> page, String username, String role, String department);

    /**
     * 根据用户名查询用户
     *
     * @param username 用户名
     * @return 用户
     */
    User getUserByUsername(String username);

    /**
     * 创建用户
     *
     * @param user 用户信息
     * @return 是否成功
     */
    boolean createUser(User user);

    /**
     * 更新用户状态
     *
     * @param id     用户ID
     * @param status 新状态
     * @return 是否成功
     */
    boolean updateStatus(Long id, Integer status);

    /**
     * 检查用户名是否存在
     *
     * @param username 用户名
     * @param excludeId 排除的ID（用于更新时）
     * @return 是否存在
     */
    boolean existsUsername(String username, Long excludeId);
}