package com.motorparts;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.web.context.WebServerApplicationContext;
import org.springframework.context.annotation.ComponentScan;
import org.springframework.transaction.annotation.EnableTransactionManagement;

/**
 * 摩托车零部件采购管理系统 - 主启动类
 *
 * @author System
 * @version 1.0.0
 */
@SpringBootApplication
@MapperScan("com.motorparts.mapper")
@ComponentScan(basePackages = "com.motorparts")
@EnableTransactionManagement
public class MotorpartsApplication {

    public static void main(String[] args) {
        WebServerApplicationContext context = (WebServerApplicationContext)
                SpringApplication.run(MotorpartsApplication.class, args);
        int port = context.getWebServer().getPort();
        String baseUrl = "http://localhost:" + port;
        System.out.println("==========================================");
        System.out.println("摩托车零部件采购管理系统启动成功！");
        System.out.println("系统访问地址: " + baseUrl);
        System.out.println("API文档地址: " + baseUrl + "/swagger-ui/index.html");
        System.out.println("==========================================");
    }
}
