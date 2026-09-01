-- Edge auto-register heartbeat + uploaded system logs
SET NAMES utf8mb4;

ALTER TABLE edge_box
    ADD COLUMN last_seen_at DATETIME NULL,
    ADD COLUMN hostname VARCHAR(128) NULL,
    ADD COLUMN agent_version VARCHAR(64) NULL,
    ADD COLUMN camera_count INT NULL,
    ADD COLUMN status_json JSON NULL;

CREATE INDEX idx_edge_box_last_seen ON edge_box (last_seen_at);

CREATE TABLE IF NOT EXISTS edge_sys_log (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    edge_box_id VARCHAR(64) NOT NULL,
    source VARCHAR(32) NOT NULL,
    body MEDIUMTEXT NOT NULL,
    collected_at DATETIME NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_edge_log_box FOREIGN KEY (edge_box_id) REFERENCES edge_box (id),
    INDEX idx_edge_log_box_time (edge_box_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
