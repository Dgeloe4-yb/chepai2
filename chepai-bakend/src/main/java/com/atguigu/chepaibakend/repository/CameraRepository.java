package com.atguigu.chepaibakend.repository;

import com.atguigu.chepaibakend.dto.CameraDtos;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Repository;

@Repository
public class CameraRepository {

    private final JdbcTemplate jdbc;

    public CameraRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<CameraDtos.CameraView> MAPPER = CameraRepository::map;

    private static CameraDtos.CameraView map(ResultSet rs, int rowNum) throws SQLException {
        int chRaw = rs.getInt("channel_no");
        Integer ch = rs.wasNull() ? null : chRaw;
        return new CameraDtos.CameraView(
                rs.getLong("id"),
                rs.getLong("site_id"),
                rs.getString("name"),
                rs.getString("rtsp_url"),
                ch,
                rs.getString("edge_box_id"),
                rs.getTimestamp("created_at").toLocalDateTime());
    }

    public List<CameraDtos.CameraView> listBySite(Long siteId) {
        if (siteId == null) {
            return jdbc.query(
                    "SELECT id, site_id, name, rtsp_url, channel_no, edge_box_id, created_at FROM camera ORDER BY id",
                    MAPPER);
        }
        return jdbc.query(
                "SELECT id, site_id, name, rtsp_url, channel_no, edge_box_id, created_at FROM camera WHERE site_id = ? ORDER BY id",
                MAPPER,
                siteId);
    }

    public List<CameraDtos.CameraView> listByEdgeBoxId(String edgeBoxId) {
        return jdbc.query(
                "SELECT id, site_id, name, rtsp_url, channel_no, edge_box_id, created_at FROM camera WHERE edge_box_id = ? ORDER BY id",
                MAPPER,
                edgeBoxId);
    }

    public List<CameraDtos.CameraView> listByEdgeBoxIds(Collection<String> edgeBoxIds) {
        if (edgeBoxIds == null || edgeBoxIds.isEmpty()) {
            return List.of();
        }
        var ids = new ArrayList<String>();
        for (String id : edgeBoxIds) {
            if (id != null && !id.isBlank()) {
                ids.add(id.trim());
            }
        }
        if (ids.isEmpty()) {
            return List.of();
        }
        String placeholders = String.join(",", ids.stream().map(x -> "?").toList());
        return jdbc.query(
                "SELECT id, site_id, name, rtsp_url, channel_no, edge_box_id, created_at FROM camera WHERE edge_box_id IN ("
                        + placeholders
                        + ") ORDER BY id",
                MAPPER,
                ids.toArray());
    }

    public CameraDtos.CameraView findById(long id) {
        List<CameraDtos.CameraView> rows =
                jdbc.query(
                        "SELECT id, site_id, name, rtsp_url, channel_no, edge_box_id, created_at FROM camera WHERE id = ?",
                        MAPPER,
                        id);
        return rows.isEmpty() ? null : rows.get(0);
    }

    public long insert(long siteId, String name, String rtspUrl, Integer channelNo, String edgeBoxId) {
        GeneratedKeyHolder kh = new GeneratedKeyHolder();
        jdbc.update(
                con -> {
                    var ps = con.prepareStatement(
                            "INSERT INTO camera (site_id, name, rtsp_url, channel_no, edge_box_id) VALUES (?,?,?,?,?)",
                            java.sql.Statement.RETURN_GENERATED_KEYS);
                    ps.setLong(1, siteId);
                    ps.setString(2, name);
                    ps.setString(3, rtspUrl);
                    if (channelNo == null) {
                        ps.setObject(4, null);
                    } else {
                        ps.setInt(4, channelNo);
                    }
                    ps.setString(5, edgeBoxId);
                    return ps;
                },
                kh);
        Number key = kh.getKey();
        if (key == null) {
            throw new IllegalStateException("Failed to obtain camera id");
        }
        return key.longValue();
    }

    public boolean update(long id, String name, String rtspUrl, Integer channelNo, String edgeBoxId) {
        int n = jdbc.update(
                "UPDATE camera SET name = ?, rtsp_url = ?, channel_no = ?, edge_box_id = ? WHERE id = ?",
                name,
                rtspUrl,
                channelNo,
                edgeBoxId,
                id);
        return n > 0;
    }
}
