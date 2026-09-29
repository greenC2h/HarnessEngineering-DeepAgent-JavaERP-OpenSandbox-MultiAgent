package com.motorparts.service.impl;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.baomidou.mybatisplus.extension.service.impl.ServiceImpl;
import com.motorparts.entity.User;
import com.motorparts.mapper.UserMapper;
import com.motorparts.service.UserService;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

/**
 * 用户/员工服务实现类
 */
@Service
public class UserServiceImpl extends ServiceImpl<UserMapper, User> implements UserService {

    @Override
    public Page<User> pageUsers(Page<User> page, String username, String role, String department) {
        LambdaQueryWrapper<User> wrapper = new LambdaQueryWrapper<>();

        if (StringUtils.hasText(username)) {
            wrapper.like(User::getUsername, username);
        }

        if (StringUtils.hasText(role)) {
            wrapper.eq(User::getRole, role);
        }

        if (StringUtils.hasText(department)) {
            wrapper.eq(User::getDepartment, department);
        }

        wrapper.orderByDesc(User::getCreateTime);

        return baseMapper.selectPage(page, wrapper);
    }

    @Override
    public User getUserByUsername(String username) {
        if (!StringUtils.hasText(username)) {
            return null;
        }

        LambdaQueryWrapper<User> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(User::getUsername, username);

        return baseMapper.selectOne(wrapper);
    }

    @Override
    public boolean createUser(User user) {
        if (user == null || !StringUtils.hasText(user.getUsername())) {
            return false;
        }

        // 检查用户名是否已存在
        if (existsUsername(user.getUsername(), null)) {
            return false;
        }

        return save(user);
    }

    @Override
    public boolean updateStatus(Long id, Integer status) {
        if (id == null || status == null) {
            return false;
        }

        LambdaUpdateWrapper<User> wrapper = new LambdaUpdateWrapper<>();
        wrapper.set(User::getStatus, status)
               .eq(User::getId, id);

        return update(wrapper);
    }

    @Override
    public boolean existsUsername(String username, Long excludeId) {
        LambdaQueryWrapper<User> wrapper = new LambdaQueryWrapper<>();
        wrapper.eq(User::getUsername, username);

        if (excludeId != null) {
            wrapper.ne(User::getId, excludeId);
        }

        return baseMapper.selectCount(wrapper) > 0;
    }
}