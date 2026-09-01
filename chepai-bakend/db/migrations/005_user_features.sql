-- Per-user feature flags (detection types synced to assigned edge boxes)
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS user_feature (
    user_id BIGINT NOT NULL,
    feature_key VARCHAR(32) NOT NULL,
    PRIMARY KEY (user_id, feature_key),
    CONSTRAINT fk_uf_user FOREIGN KEY (user_id) REFERENCES app_user (id),
    INDEX idx_uf_key (feature_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO user_feature (user_id, feature_key)
SELECT u.id, k.feature_key
FROM app_user u
CROSS JOIN (
    SELECT 'oil_car' AS feature_key
    UNION ALL SELECT 'bad_park'
    UNION ALL SELECT 'mini_ad'
    UNION ALL SELECT 'dual_slot'
    UNION ALL SELECT 'car_in_bus_slot'
    UNION ALL SELECT 'bus_in_restricted'
) k
WHERE u.role = 'USER' AND u.enabled = 1;
