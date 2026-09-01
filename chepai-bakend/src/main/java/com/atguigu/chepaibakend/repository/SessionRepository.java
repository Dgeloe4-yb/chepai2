package com.atguigu.chepaibakend.repository;

import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.util.HexFormat;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class SessionRepository {

    public record SessionRow(String token, long userId, LocalDateTime expiresAt) {}

    private static final SecureRandom RNG = new SecureRandom();
    private final JdbcTemplate jdbc;

    public SessionRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public static String newToken() {
        byte[] buf = new byte[32];
        RNG.nextBytes(buf);
        return HexFormat.of().formatHex(buf);
    }

    public SessionRow findValid(String token) {
        if (token == null || token.isBlank()) {
            return null;
        }
        List<SessionRow> rows =
                jdbc.query(
                        "SELECT token, user_id, expires_at FROM user_session WHERE token = ? AND expires_at > NOW()",
                        (rs, i) ->
                                new SessionRow(
                                        rs.getString("token"),
                                        rs.getLong("user_id"),
                                        rs.getTimestamp("expires_at").toLocalDateTime()),
                        token);
        return rows.isEmpty() ? null : rows.get(0);
    }

    public String create(long userId, int days) {
        String token = newToken();
        jdbc.update(
                "INSERT INTO user_session (token, user_id, expires_at) VALUES (?, ?, DATE_ADD(NOW(), INTERVAL ? DAY))",
                token,
                userId,
                Math.max(1, days));
        return token;
    }

    public void delete(String token) {
        if (token == null || token.isBlank()) {
            return;
        }
        jdbc.update("DELETE FROM user_session WHERE token = ?", token);
    }
}
