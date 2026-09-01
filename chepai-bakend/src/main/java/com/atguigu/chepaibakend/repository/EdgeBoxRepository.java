package com.atguigu.chepaibakend.repository;

import com.atguigu.chepaibakend.dto.AuthDtos;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

@Repository
public class EdgeBoxRepository {

    private String selectCols() {
        return """
                b.id, b.name, b.created_at, b.last_seen_at, b.hostname, b.agent_version,
                b.camera_count, b.status_json,
                (b.last_seen_at IS NOT NULL AND b.last_seen_at > DATE_SUB(NOW(), INTERVAL %d SECOND)) AS online
                """
                .formatted(onlineSeconds);
    }

    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;
    private final int onlineSeconds;

    public EdgeBoxRepository(
            JdbcTemplate jdbc,
            ObjectMapper objectMapper,
            @Value("${chepai.edge.online-seconds:90}") int onlineSeconds) {
        this.jdbc = jdbc;
        this.objectMapper = objectMapper;
        this.onlineSeconds = Math.max(15, onlineSeconds);
    }

    private RowMapper<AuthDtos.EdgeBoxView> mapper() {
        return this::map;
    }

    private AuthDtos.EdgeBoxView map(ResultSet rs, int i) throws SQLException {
        return new AuthDtos.EdgeBoxView(
                rs.getString("id"),
                rs.getString("name"),
                toLocal(rs.getTimestamp("created_at")),
                toLocal(rs.getTimestamp("last_seen_at")),
                rs.getString("hostname"),
                rs.getString("agent_version"),
                getInteger(rs, "camera_count"),
                rs.getBoolean("online"),
                parseJson(rs.getString("status_json")));
    }

    public List<AuthDtos.EdgeBoxView> listAll() {
        return jdbc.query("SELECT " + selectCols() + " FROM edge_box b ORDER BY b.id", mapper());
    }

    public AuthDtos.EdgeBoxView findById(String id) {
        List<AuthDtos.EdgeBoxView> rows =
                jdbc.query("SELECT " + selectCols() + " FROM edge_box b WHERE b.id = ?", mapper(), id);
        return rows.isEmpty() ? null : rows.get(0);
    }

    public void upsert(String id, String name) {
        jdbc.update(
                """
                INSERT INTO edge_box (id, name) VALUES (?, ?)
                ON DUPLICATE KEY UPDATE name = VALUES(name)
                """,
                id,
                name);
    }

    public void touchHeartbeat(
            String id,
            String name,
            String hostname,
            String agentVersion,
            Integer cameraCount,
            String statusJson) {
        jdbc.update(
                """
                INSERT INTO edge_box (id, name, last_seen_at, hostname, agent_version, camera_count, status_json)
                VALUES (?, ?, NOW(), ?, ?, ?, CAST(? AS JSON))
                ON DUPLICATE KEY UPDATE
                    last_seen_at = NOW(),
                    hostname = COALESCE(VALUES(hostname), hostname),
                    agent_version = COALESCE(VALUES(agent_version), agent_version),
                    camera_count = COALESCE(VALUES(camera_count), camera_count),
                    status_json = IF(VALUES(status_json) IS NULL, status_json, VALUES(status_json))
                """,
                id,
                name,
                hostname,
                agentVersion,
                cameraCount,
                statusJson);
    }

    public List<String> listIdsForUser(long userId) {
        return jdbc.query(
                "SELECT edge_box_id FROM user_edge_box WHERE user_id = ? ORDER BY edge_box_id",
                (rs, i) -> rs.getString("edge_box_id"),
                userId);
    }

    public List<AuthDtos.EdgeBoxView> listForUser(long userId) {
        return jdbc.query(
                "SELECT "
                        + selectCols()
                        + """
                         FROM edge_box b
                         INNER JOIN user_edge_box a ON a.edge_box_id = b.id
                         WHERE a.user_id = ?
                         ORDER BY b.id
                         """,
                mapper(),
                userId);
    }

    @Transactional
    public void replaceUserBoxes(long userId, List<String> edgeBoxIds) {
        jdbc.update("DELETE FROM user_edge_box WHERE user_id = ?", userId);
        if (edgeBoxIds == null) {
            return;
        }
        for (String id : edgeBoxIds) {
            if (id == null || id.isBlank()) {
                continue;
            }
            jdbc.update(
                    "INSERT INTO user_edge_box (user_id, edge_box_id) VALUES (?, ?)", userId, id.trim());
        }
    }

    public boolean userOwns(long userId, String edgeBoxId) {
        Long n =
                jdbc.queryForObject(
                        "SELECT COUNT(*) FROM user_edge_box WHERE user_id = ? AND edge_box_id = ?",
                        Long.class,
                        userId,
                        edgeBoxId);
        return n != null && n > 0;
    }

    private static LocalDateTime toLocal(Timestamp ts) {
        return ts == null ? null : ts.toLocalDateTime();
    }

    private static Integer getInteger(ResultSet rs, String col) throws SQLException {
        Object v = rs.getObject(col);
        if (v == null) {
            return null;
        }
        return ((Number) v).intValue();
    }

    private JsonNode parseJson(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        try {
            return objectMapper.readTree(raw);
        } catch (Exception ex) {
            return objectMapper.nullNode();
        }
    }
}
