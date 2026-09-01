package com.atguigu.chepaibakend.repository;

import com.atguigu.chepaibakend.dto.SiteDtos;
import java.sql.ResultSet;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.stereotype.Repository;

@Repository
public class SiteRepository {

    private final JdbcTemplate jdbc;

    public SiteRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<SiteDtos.SiteView> MAPPER =
            (rs, rowNum) -> new SiteDtos.SiteView(
                    rs.getLong("id"),
                    rs.getString("name"),
                    rs.getString("address"),
                    rs.getTimestamp("created_at").toLocalDateTime());

    public List<SiteDtos.SiteView> listAll() {
        return jdbc.query("SELECT id, name, address, created_at FROM site ORDER BY id", MAPPER);
    }

    public long insert(String name, String address) {
        GeneratedKeyHolder kh = new GeneratedKeyHolder();
        jdbc.update(
                con -> {
                    var ps = con.prepareStatement(
                            "INSERT INTO site (name, address) VALUES (?, ?)", java.sql.Statement.RETURN_GENERATED_KEYS);
                    ps.setString(1, name);
                    ps.setString(2, address);
                    return ps;
                },
                kh);
        Number key = kh.getKey();
        if (key == null) {
            throw new IllegalStateException("Failed to obtain site id");
        }
        return key.longValue();
    }
}
