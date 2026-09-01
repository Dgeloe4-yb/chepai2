package com.atguigu.chepaibakend.repository;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class RuleThresholdRepository {

    private final JdbcTemplate jdbc;

    public RuleThresholdRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /** Global defaults (camera_id IS NULL) overridden by per-camera rows. */
    public Map<String, String> resolveRules(Long cameraId) {
        List<Map<String, Object>> rows = jdbc.queryForList(
                "SELECT camera_id, rule_key, rule_value FROM rule_threshold WHERE camera_id IS NULL"
                        + (cameraId == null ? "" : " OR camera_id = ?"),
                cameraId == null ? new Object[] {} : new Object[] {cameraId});

        Map<String, String> global = new HashMap<>();
        Map<String, String> perCam = new HashMap<>();
        for (Map<String, Object> row : rows) {
            Object cam = row.get("camera_id");
            String key = String.valueOf(row.get("rule_key"));
            String val = String.valueOf(row.get("rule_value"));
            if (cam == null) {
                global.put(key, val);
            } else {
                perCam.put(key, val);
            }
        }
        Map<String, String> merged = new HashMap<>(global);
        merged.putAll(perCam);
        return merged;
    }
}
