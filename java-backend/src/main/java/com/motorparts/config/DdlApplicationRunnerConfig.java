package com.motorparts.config;

import com.baomidou.mybatisplus.extension.ddl.IDdl;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import javax.sql.DataSource;
import java.util.Collections;
import java.util.List;
import java.util.function.Consumer;

/**
 * 配置类，用于解决ddlApplicationRunner的问题
 */
@Configuration
public class DdlApplicationRunnerConfig {

    /**
     * MyBatis-Plus 3.5.3.1 在没有 IDdl 实现时会返回 NullBean，
     * Spring Boot 会因此在启动回调阶段失败。提供空实现即可保留正常启动流程。
     */
    @Bean
    public IDdl emptyDdl() {
        return new IDdl() {
            @Override
            public void runScript(Consumer<DataSource> consumer) {
                // 项目使用 DatabaseInitializer 管理建表和数据初始化。
            }

            @Override
            public List<String> getSqlFiles() {
                return Collections.emptyList();
            }
        };
    }
}
