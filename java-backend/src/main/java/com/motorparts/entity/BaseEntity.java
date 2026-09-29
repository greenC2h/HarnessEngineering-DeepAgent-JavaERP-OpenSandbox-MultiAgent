package com.motorparts.entity;

import com.baomidou.mybatisplus.annotation.FieldFill;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.databind.annotation.JsonDeserialize;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;

import java.io.Serializable;
import java.time.LocalDateTime;

/**
 * 基础实体类，包含公共字段
 */
public abstract class BaseEntity implements Serializable {

    private static final long serialVersionUID = 1L;

    @TableLogic
    @TableField(value = "deleted", fill = FieldFill.INSERT)
    private Integer deleted;

    @JsonFormat(pattern = "yyyy-MM-dd'T'HH:mm:ss.SSS")
    @TableField(value = "create_time", fill = FieldFill.INSERT)
    @JsonDeserialize(using = com.motorparts.common.CustomLocalDateTimeDeserializer.class)
    @JsonSerialize(using = com.motorparts.common.CustomLocalDateTimeSerializer.class)
    private LocalDateTime createTime;

    @JsonFormat(pattern = "yyyy-MM-dd'T'HH:mm:ss.SSS")
    @TableField(value = "update_time", fill = FieldFill.INSERT_UPDATE)
    @JsonDeserialize(using = com.motorparts.common.CustomLocalDateTimeDeserializer.class)
    @JsonSerialize(using = com.motorparts.common.CustomLocalDateTimeSerializer.class)
    private LocalDateTime updateTime;

    public Integer getDeleted() {
        return deleted;
    }

    public void setDeleted(Integer deleted) {
        this.deleted = deleted;
    }

    public LocalDateTime getCreateTime() {
        return createTime;
    }

    public void setCreateTime(LocalDateTime createTime) {
        this.createTime = createTime;
    }

    public LocalDateTime getUpdateTime() {
        return updateTime;
    }

    public void setUpdateTime(LocalDateTime updateTime) {
        this.updateTime = updateTime;
    }
}