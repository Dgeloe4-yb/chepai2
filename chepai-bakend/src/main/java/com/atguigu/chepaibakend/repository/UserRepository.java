package com.atguigu.chepaibakend.repository;

import com.atguigu.chepaibakend.dto.AuthDtos;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Repository;

@Repository
public class UserRepository {

    public record UserRow(
            long id,
            String username,
            String passwordHash,
            String displayName,
            String role,
            boolean enabled) {}

    private final JdbcTemplate jdbc;

    public UserRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<UserRow> ROW = UserRepository::mapRow;
    private static final RowMapper<AuthDtos.UserView> VIEW = UserRepository::mapView;

    private static UserRow mapRow(ResultSet rs, int i) throws SQLException {
        return new UserRow(
                rs.getLong("id"),
                rs.getString("username"),
                rs.getString("password_hash"),
                rs.getString("display_name"),
                rs.getString("role"),
                rs.getInt("enabled") != 0);
    }

    private static AuthDtos.UserView mapView(ResultSet rs, int i) throws SQLException {
        return new AuthDtos.UserView(
                rs.getLong("id"),
                rs.getString("username"),
                rs.getString("display_name"),
                rs.getString("role"),
                rs.getInt("enabled") != 0,
                rs.getTimestamp("created_at").toLocalDateTime(),
                List.of());
    }

    public long count() {
        Long n = jdbc.queryForObject("SELECT COUNT(*) FROM app_user", Long.class);
        return n == null ? 0 : n;
    }

    public UserRow findById(long id) {
        List<UserRow> rows =
                jdbc.query(
                        "SELECT id, username, password_hash, display_name, role, enabled FROM app_user WHERE id = ?",
                        ROW,
                        id);
        return rows.isEmpty() ? null : rows.get(0);
    }

    public UserRow findByUsername(String username) {
        List<UserRow> rows =
                jdbc.query(
                        "SELECT id, username, password_hash, display_name, role, enabled FROM app_user WHERE username = ?",
                        ROW,
                        username);
        return rows.isEmpty() ? null : rows.get(0);
    }

    public AuthDtos.UserView viewById(long id) {
        List<AuthDtos.UserView> rows =
                jdbc.query(
                        "SELECT id, username, display_name, role, enabled, created_at FROM app_user WHERE id = ?",
                        VIEW,
                        id);
        return rows.isEmpty() ? null : rows.get(0);
    }

    public List<AuthDtos.UserView> listAll() {
        return jdbc.query(
                "SELECT id, username, display_name, role, enabled, created_at FROM app_user ORDER BY id", VIEW);
    }

    public long insert(String username, String passwordHash, String displayName, String role) {
        GeneratedKeyHolder kh = new GeneratedKeyHolder();
        jdbc.update(
                con -> {
                    var ps =
                            con.prepareStatement(
                                    "INSERT INTO app_user (username, password_hash, display_name, role, enabled) VALUES (?,?,?,?,1)",
                                    java.sql.Statement.RETURN_GENERATED_KEYS);
                    ps.setString(1, username);
                    ps.setString(2, passwordHash);
                    ps.setString(3, displayName);
                    ps.setString(4, role);
                    return ps;
                },
                kh);
        Number key = kh.getKey();
        if (key == null) {
            throw new IllegalStateException("Failed to obtain user id");
        }
        return key.longValue();
    }

    public boolean update(long id, String displayName, String passwordHash, Boolean enabled) {
        UserRow existing = findById(id);
        if (existing == null) {
            return false;
        }
        String name = displayName != null ? displayName : existing.displayName();
        String hash = passwordHash != null ? passwordHash : existing.passwordHash();
        int en = enabled != null ? (enabled ? 1 : 0) : (existing.enabled() ? 1 : 0);
        int n =
                jdbc.update(
                        "UPDATE app_user SET display_name = ?, password_hash = ?, enabled = ? WHERE id = ?",
                        name,
                        hash,
                        en,
                        id);
        return n > 0;
    }
}
