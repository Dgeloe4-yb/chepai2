-- Users, edge-box assignment, custom voice clips (MySQL 8+)
SET NAMES utf8mb4;

CREATE TABLE IF NOT EXISTS app_user (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    username VARCHAR(64) NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(128) NULL,
    role VARCHAR(16) NOT NULL COMMENT 'SUPER_ADMIN | USER',
    enabled TINYINT(1) NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_app_user_username (username)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_session (
    token CHAR(64) NOT NULL PRIMARY KEY,
    user_id BIGINT NOT NULL,
    expires_at DATETIME NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_session_user FOREIGN KEY (user_id) REFERENCES app_user (id),
    INDEX idx_session_user (user_id),
    INDEX idx_session_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS edge_box (
    id VARCHAR(64) NOT NULL PRIMARY KEY COMMENT 'matches camera.edge_box_id / CHEPAI_EDGE_BOX_ID',
    name VARCHAR(128) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_edge_box (
    user_id BIGINT NOT NULL,
    edge_box_id VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, edge_box_id),
    CONSTRAINT fk_ueb_user FOREIGN KEY (user_id) REFERENCES app_user (id),
    CONSTRAINT fk_ueb_box FOREIGN KEY (edge_box_id) REFERENCES edge_box (id),
    INDEX idx_ueb_box (edge_box_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS voice_clip (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    edge_box_id VARCHAR(64) NOT NULL,
    alert_type VARCHAR(32) NOT NULL,
    original_name VARCHAR(255) NULL,
    stored_name VARCHAR(128) NOT NULL,
    sha256 CHAR(64) NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT fk_voice_box FOREIGN KEY (edge_box_id) REFERENCES edge_box (id),
    UNIQUE KEY uk_voice_box_type (edge_box_id, alert_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
