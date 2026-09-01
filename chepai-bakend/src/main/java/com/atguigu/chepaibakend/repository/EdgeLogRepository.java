package com.atguigu.chepaibakend.repository;

import com.atguigu.chepaibakend.dto.EdgeDtos;
import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

@Repository
public class EdgeLogRepository {

    private static final RowMapper<EdgeDtos.EdgeLogView> MAPPER =
            (rs, i) ->
                    new EdgeDtos.EdgeLogView(
                            rs.getLong("id"),
                            rs.getString("edge_box_id"),
                            rs.getString("source"),
                            rs.getString("body"),
                            rs.getTimestamp("collected_at").toLocalDateTime(),
                            rs.getTimestamp("created_at").toLocalDateTime());

    private final JdbcTemplate jdbc;
    private final int keep;

    public EdgeLogRepository(
            JdbcTemplate jdbc, @Value("${chepai.edge.log-keep:40}") int keep) {
        this.jdbc = jdbc;
        this.keep = Math.max(5, keep);
    }

    public void insert(String edgeBoxId, String source, String body, LocalDateTime collectedAt) {
        LocalDateTime when = collectedAt == null ? LocalDateTime.now() : collectedAt;
        jdbc.update(
                """
                INSERT INTO edge_sys_log (edge_box_id, source, body, collected_at)
                VALUES (?, ?, ?, ?)
                """,
                edgeBoxId,
                source,
                body,
                Timestamp.valueOf(when));
        jdbc.update(
                """
                DELETE FROM edge_sys_log
                WHERE edge_box_id = ?
                  AND id NOT IN (
                    SELECT id FROM (
                        SELECT id FROM edge_sys_log WHERE edge_box_id = ? ORDER BY id DESC LIMIT ?
                    ) t
                  )
                """,
                edgeBoxId,
                edgeBoxId,
                keep);
    }

    public List<EdgeDtos.EdgeLogView> listByBox(String edgeBoxId, int limit) {
        int n = limit <= 0 || limit > 100 ? 20 : limit;
        return jdbc.query(
                """
                SELECT id, edge_box_id, source, body, collected_at, created_at
                FROM edge_sys_log
                WHERE edge_box_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                MAPPER,
                edgeBoxId,
                n);
    }

    public int deleteOlderThanDays(int days) {
        if (days <= 0) {
            return 0;
        }
        return jdbc.update(
                "DELETE FROM edge_sys_log WHERE created_at < DATE_SUB(NOW(), INTERVAL ? DAY)", days);
    }
}
