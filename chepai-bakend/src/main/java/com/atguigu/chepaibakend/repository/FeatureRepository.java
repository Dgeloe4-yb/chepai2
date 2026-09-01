package com.atguigu.chepaibakend.repository;

import com.atguigu.chepaibakend.config.FeatureCatalog;
import java.util.ArrayList;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

@Repository
public class FeatureRepository {

    private final JdbcTemplate jdbc;

    public FeatureRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public List<String> listForUser(long userId) {
        return jdbc.query(
                "SELECT feature_key FROM user_feature WHERE user_id = ? ORDER BY feature_key",
                (rs, i) -> rs.getString("feature_key"),
                userId);
    }

    public boolean userHas(long userId, String featureKey) {
        Long n =
                jdbc.queryForObject(
                        "SELECT COUNT(*) FROM user_feature WHERE user_id = ? AND feature_key = ?",
                        Long.class,
                        userId,
                        featureKey);
        return n != null && n > 0;
    }

    /**
     * Features the box should run: union of enabled USER accounts assigned to it.
     * No assignees → all features (site keeps detecting before any user is bound).
     */
    public List<String> listForBox(String edgeBoxId) {
        Long assigned =
                jdbc.queryForObject(
                        """
                        SELECT COUNT(*) FROM user_edge_box a
                        INNER JOIN app_user u ON u.id = a.user_id
                        WHERE a.edge_box_id = ? AND u.role = 'USER' AND u.enabled = 1
                        """,
                        Long.class,
                        edgeBoxId);
        if (assigned == null || assigned == 0) {
            return FeatureCatalog.ALL;
        }
        return jdbc.query(
                """
                SELECT DISTINCT f.feature_key
                FROM user_feature f
                INNER JOIN user_edge_box a ON a.user_id = f.user_id
                INNER JOIN app_user u ON u.id = f.user_id
                WHERE a.edge_box_id = ? AND u.role = 'USER' AND u.enabled = 1
                ORDER BY f.feature_key
                """,
                (rs, i) -> rs.getString("feature_key"),
                edgeBoxId);
    }

    @Transactional
    public void replaceForUser(long userId, List<String> keys) {
        jdbc.update("DELETE FROM user_feature WHERE user_id = ?", userId);
        if (keys == null) {
            return;
        }
        for (String raw : keys) {
            if (raw == null || raw.isBlank() || !FeatureCatalog.isKnown(raw.trim())) {
                continue;
            }
            jdbc.update(
                    "INSERT INTO user_feature (user_id, feature_key) VALUES (?, ?)",
                    userId,
                    raw.trim());
        }
    }

    public void grantAll(long userId) {
        replaceForUser(userId, new ArrayList<>(FeatureCatalog.ALL));
    }
}
