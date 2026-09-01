package com.atguigu.chepaibakend.web;

import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class HealthController {

    private final JdbcTemplate jdbc;

    public HealthController(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @GetMapping("/health")
    public Map<String, Object> health() {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("service", "chepai-bakend");
        try {
            jdbc.queryForObject("SELECT 1", Integer.class);
            body.put("database", "UP");
            body.put("status", "UP");
        } catch (Exception ex) {
            body.put("database", "DOWN");
            body.put("status", "DOWN");
            body.put("error", ex.getClass().getSimpleName());
        }
        return body;
    }
}
