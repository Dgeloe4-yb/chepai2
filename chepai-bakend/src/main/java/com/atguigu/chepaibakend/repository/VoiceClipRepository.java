package com.atguigu.chepaibakend.repository;

import com.atguigu.chepaibakend.dto.AuthDtos;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

@Repository
public class VoiceClipRepository {

    public record VoiceRow(
            long id, String edgeBoxId, String alertType, String originalName, String storedName, String sha256) {}

    private static final RowMapper<AuthDtos.VoiceClipView> VIEW =
            (rs, i) ->
                    new AuthDtos.VoiceClipView(
                            rs.getString("edge_box_id"),
                            rs.getString("alert_type"),
                            rs.getString("original_name"),
                            rs.getString("sha256"),
                            rs.getTimestamp("updated_at").toLocalDateTime());

    private static final RowMapper<VoiceRow> ROW =
            (rs, i) ->
                    new VoiceRow(
                            rs.getLong("id"),
                            rs.getString("edge_box_id"),
                            rs.getString("alert_type"),
                            rs.getString("original_name"),
                            rs.getString("stored_name"),
                            rs.getString("sha256"));

    private final JdbcTemplate jdbc;

    public VoiceClipRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public List<AuthDtos.VoiceClipView> listByBox(String edgeBoxId) {
        return jdbc.query(
                "SELECT edge_box_id, alert_type, original_name, sha256, updated_at FROM voice_clip WHERE edge_box_id = ? ORDER BY alert_type",
                VIEW,
                edgeBoxId);
    }

    public VoiceRow find(String edgeBoxId, String alertType) {
        List<VoiceRow> rows =
                jdbc.query(
                        "SELECT id, edge_box_id, alert_type, original_name, stored_name, sha256 FROM voice_clip WHERE edge_box_id = ? AND alert_type = ?",
                        ROW,
                        edgeBoxId,
                        alertType);
        return rows.isEmpty() ? null : rows.get(0);
    }

    public void upsert(
            String edgeBoxId, String alertType, String originalName, String storedName, String sha256) {
        jdbc.update(
                """
                INSERT INTO voice_clip (edge_box_id, alert_type, original_name, stored_name, sha256)
                VALUES (?, ?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE
                    original_name = VALUES(original_name),
                    stored_name = VALUES(stored_name),
                    sha256 = VALUES(sha256),
                    updated_at = CURRENT_TIMESTAMP
                """,
                edgeBoxId,
                alertType,
                originalName,
                storedName,
                sha256);
    }
}
