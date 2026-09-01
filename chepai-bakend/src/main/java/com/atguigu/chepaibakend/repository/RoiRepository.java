package com.atguigu.chepaibakend.repository;

import com.atguigu.chepaibakend.dto.RoiDtos;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Repository;

@Repository
public class RoiRepository {

    private final JdbcTemplate jdbc;
    private final ObjectMapper objectMapper;

    public RoiRepository(JdbcTemplate jdbc, ObjectMapper objectMapper) {
        this.jdbc = jdbc;
        this.objectMapper = objectMapper;
    }

    private RowMapper<RoiDtos.RoiView> mapper() {
        return this::map;
    }

    private RoiDtos.RoiView map(ResultSet rs, int rowNum) throws SQLException {
        String polygon = readJsonAsString(rs, "polygon_json");
        return new RoiDtos.RoiView(
                rs.getLong("id"),
                rs.getLong("camera_id"),
                rs.getString("region_type"),
                rs.getString("name"),
                polygon,
                rs.getTimestamp("created_at").toLocalDateTime());
    }

    private String readJsonAsString(ResultSet rs, String col) throws SQLException {
        String s = rs.getString(col);
        return s == null ? null : s;
    }

    public List<RoiDtos.RoiView> listByCamera(Long cameraId) {
        return jdbc.query(
                "SELECT id, camera_id, region_type, name, polygon_json, created_at FROM roi_region WHERE camera_id = ? ORDER BY id",
                mapper(),
                cameraId);
    }

    public long insert(long cameraId, String regionType, String name, String polygonJsonString) {
        JsonNode node;
        try {
            node = objectMapper.readTree(polygonJsonString);
        } catch (Exception e) {
            throw new IllegalArgumentException("polygonJson must be valid JSON");
        }
        if (!node.isArray() && !node.isObject()) {
            throw new IllegalArgumentException("polygonJson must be JSON array or object");
        }

        GeneratedKeyHolder kh = new GeneratedKeyHolder();
        jdbc.update(
                con -> {
                    var ps = con.prepareStatement(
                            "INSERT INTO roi_region (camera_id, region_type, name, polygon_json) VALUES (?,?,?, CAST(? AS JSON))",
                            java.sql.Statement.RETURN_GENERATED_KEYS);
                    ps.setLong(1, cameraId);
                    ps.setString(2, regionType);
                    ps.setString(3, name);
                    ps.setString(4, polygonJsonString);
                    return ps;
                },
                kh);
        Number key = kh.getKey();
        if (key == null) {
            throw new IllegalStateException("Failed to obtain roi id");
        }
        return key.longValue();
    }

    public boolean delete(long id) {
        return jdbc.update("DELETE FROM roi_region WHERE id = ?", id) > 0;
    }
}
