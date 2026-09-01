-- 充电站视觉监控 - 核心表（MySQL 8+）
-- 可经 MCP MySQL 或 mysql 客户端在库 chepai 中执行

SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS site (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    name VARCHAR(128) NOT NULL,
    address VARCHAR(255),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS camera (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    site_id BIGINT NOT NULL,
    name VARCHAR(128) NOT NULL,
    rtsp_url VARCHAR(512),
    channel_no INT,
    edge_box_id VARCHAR(64),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_camera_site FOREIGN KEY (site_id) REFERENCES site (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS roi_region (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    camera_id BIGINT NOT NULL,
    region_type VARCHAR(32) NOT NULL COMMENT 'parking=车位,pile=充电桩区,full=全幅或其它',
    name VARCHAR(128),
    polygon_json JSON NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_roi_camera FOREIGN KEY (camera_id) REFERENCES camera (id),
    INDEX idx_roi_camera (camera_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS alert_event (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    camera_id BIGINT NOT NULL,
    alert_type VARCHAR(32) NOT NULL COMMENT 'oil_car,gun_misplace,bad_park,non_sedan',
    score DOUBLE,
    snapshot_path VARCHAR(512),
    raw_json JSON,
    idempotency_key VARCHAR(128),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_alert_camera FOREIGN KEY (camera_id) REFERENCES camera (id),
    INDEX idx_alert_cam_time (camera_id, created_at),
    INDEX idx_alert_type (alert_type),
    UNIQUE KEY uk_alert_idempotency (idempotency_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS rule_threshold (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    camera_id BIGINT NULL COMMENT 'NULL 表示全局默认',
    rule_key VARCHAR(64) NOT NULL,
    rule_value VARCHAR(512) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_rule_camera FOREIGN KEY (camera_id) REFERENCES camera (id),
    UNIQUE KEY uk_rule_cam_key (camera_id, rule_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
