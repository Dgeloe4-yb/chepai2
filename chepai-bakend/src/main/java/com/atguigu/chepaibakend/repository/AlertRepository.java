package com.atguigu.chepaibakend.repository;

import com.atguigu.chepaibakend.dto.AlertDtos;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Repository;

@Repository
public class AlertRepository {

    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;

    public AlertRepository(JdbcTemplate jdbc, ObjectMapper objectMapper) {
        this.jdbc = jdbc;
        this.objectMapper = objectMapper;
    }

    private RowMapper<AlertDtos.AlertView> mapper() {
        return this::map;
    }

    private AlertDtos.AlertView map(ResultSet rs, int rowNum) throws SQLException {
        JsonNode raw = null;
        String rawStr = rs.getString("raw_json");
        if (rawStr != null) {
            try {
                raw = objectMapper.readTree(rawStr);
            } catch (Exception ignored) {
                raw = objectMapper.nullNode();
            }
        }
        Double score = rs.getObject("score") != null ? rs.getDouble("score") : null;
        return new AlertDtos.AlertView(
                rs.getLong("id"),
                rs.getLong("camera_id"),
                rs.getString("alert_type"),
                score,
                rs.getString("snapshot_path"),
                raw,
                rs.getTimestamp("created_at").toLocalDateTime());
    }

    public AlertDtos.PageResult<AlertDtos.AlertView> search(
            Long cameraId,
            String alertType,
            LocalDateTime from,
            LocalDateTime to,
            int page,
            int size,
            Collection<String> edgeBoxIds,
            Collection<String> allowedAlertTypes) {
        if (page < 0) {
            page = 0;
        }
        if (size <= 0 || size > 200) {
            size = 20;
        }
        if (edgeBoxIds != null && edgeBoxIds.isEmpty()) {
            return new AlertDtos.PageResult<>(List.of(), 0, page, size);
        }
        if (allowedAlertTypes != null && allowedAlertTypes.isEmpty()) {
            return new AlertDtos.PageResult<>(List.of(), 0, page, size);
        }
        int offset = page * size;

        var where = new StringBuilder("WHERE 1=1");
        var args = new ArrayList<Object>();
        if (cameraId != null) {
            where.append(" AND camera_id = ?");
            args.add(cameraId);
        }
        if (edgeBoxIds != null) {
            var ids = new ArrayList<String>();
            for (String id : edgeBoxIds) {
                if (id != null && !id.isBlank()) {
                    ids.add(id.trim());
                }
            }
            if (ids.isEmpty()) {
                return new AlertDtos.PageResult<>(List.of(), 0, page, size);
            }
            where.append(" AND camera_id IN (SELECT id FROM camera WHERE edge_box_id IN (");
            for (int i = 0; i < ids.size(); i++) {
                if (i > 0) {
                    where.append(',');
                }
                where.append('?');
                args.add(ids.get(i));
            }
            where.append("))");
        }
        if (alertType != null && !alertType.isBlank()) {
            if (allowedAlertTypes != null && !allowedAlertTypes.contains(alertType)) {
                return new AlertDtos.PageResult<>(List.of(), 0, page, size);
            }
            where.append(" AND alert_type = ?");
            args.add(alertType);
        } else if (allowedAlertTypes != null) {
            where.append(" AND alert_type IN (");
            int i = 0;
            for (String t : allowedAlertTypes) {
                if (t == null || t.isBlank()) {
                    continue;
                }
                if (i > 0) {
                    where.append(',');
                }
                where.append('?');
                args.add(t);
                i++;
            }
            where.append(')');
            if (i == 0) {
                return new AlertDtos.PageResult<>(List.of(), 0, page, size);
            }
        }
        if (from != null) {
            where.append(" AND created_at >= ?");
            args.add(Timestamp.valueOf(from));
        }
        if (to != null) {
            where.append(" AND created_at <= ?");
            args.add(Timestamp.valueOf(to));
        }

        Long total = jdbc.queryForObject("SELECT COUNT(*) FROM alert_event " + where, Long.class, args.toArray());

        String sql =
                "SELECT id, camera_id, alert_type, score, snapshot_path, raw_json, created_at FROM alert_event "
                        + where
                        + " ORDER BY id DESC LIMIT ? OFFSET ?";
        args.add(size);
        args.add(offset);
        List<AlertDtos.AlertView> content = jdbc.query(sql, mapper(), args.toArray());
        return new AlertDtos.PageResult<>(content, total == null ? 0 : total, page, size);
    }

    public long insert(
            long cameraId,
            String alertType,
            Double score,
            String snapshotPath,
            JsonNode rawJson,
            String idempotencyKey) {
        String key = normalizeIdempotencyKey(idempotencyKey);
        if (key != null) {
            Long existing = findIdByIdempotencyKey(key);
            if (existing != null) {
                return existing;
            }
        }
        try {
            return insertNew(cameraId, alertType, score, snapshotPath, rawJson, key);
        } catch (DuplicateKeyException ex) {
            if (key == null) {
                throw ex;
            }
            Long existing = findIdByIdempotencyKey(key);
            if (existing != null) {
                return existing;
            }
            throw ex;
        }
    }

    public int deleteOlderThanDays(int days) {
        if (days <= 0) {
            return 0;
        }
        return jdbc.update(
                "DELETE FROM alert_event WHERE created_at < DATE_SUB(NOW(), INTERVAL ? DAY)", days);
    }

    public List<String> listSnapshotPathsOlderThanDays(int days) {
        if (days <= 0) {
            return List.of();
        }
        return jdbc.query(
                "SELECT snapshot_path FROM alert_event WHERE created_at < DATE_SUB(NOW(), INTERVAL ? DAY) AND snapshot_path IS NOT NULL",
                (rs, rowNum) -> rs.getString("snapshot_path"),
                days);
    }

    private static String normalizeIdempotencyKey(String idempotencyKey) {
        if (idempotencyKey == null) {
            return null;
        }
        String trimmed = idempotencyKey.trim();
        return trimmed.isEmpty() ? null : trimmed;
    }

    private Long findIdByIdempotencyKey(String key) {
        List<Long> ids =
                jdbc.query("SELECT id FROM alert_event WHERE idempotency_key = ? LIMIT 1", (rs, rowNum) -> rs.getLong("id"), key);
        return ids.isEmpty() ? null : ids.get(0);
    }

    private long insertNew(
            long cameraId,
            String alertType,
            Double score,
            String snapshotPath,
            JsonNode rawJson,
            String idempotencyKey) {
        String rawStr = rawJson == null || rawJson.isNull() ? null : rawJson.toString();
        GeneratedKeyHolder kh = new GeneratedKeyHolder();
        jdbc.update(
                con -> {
                    var ps = con.prepareStatement(
                            "INSERT INTO alert_event (camera_id, alert_type, score, snapshot_path, raw_json, idempotency_key) VALUES (?,?,?,?, CAST(? AS JSON),?)",
                            java.sql.Statement.RETURN_GENERATED_KEYS);
                    ps.setLong(1, cameraId);
                    ps.setString(2, alertType);
                    if (score == null) {
                        ps.setObject(3, null);
                    } else {
                        ps.setDouble(3, score);
                    }
                    ps.setString(4, snapshotPath);
                    ps.setString(5, rawStr);
                    ps.setString(6, idempotencyKey);
                    return ps;
                },
                kh);
        Number key = kh.getKey();
        if (key == null) {
            throw new IllegalStateException("Failed to obtain alert id");
        }
        return key.longValue();
    }
}
