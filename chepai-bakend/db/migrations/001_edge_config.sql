-- Edge agent support: index + default thresholds
-- Apply via MCP MySQL or mysql client on database chepai

SET NAMES utf8mb4;

CREATE INDEX idx_camera_edge_box ON camera (edge_box_id);

INSERT INTO rule_threshold (camera_id, rule_key, rule_value)
SELECT NULL, 'min_park_iou', '0.2'
WHERE NOT EXISTS (
    SELECT 1 FROM rule_threshold WHERE camera_id IS NULL AND rule_key = 'min_park_iou'
);

INSERT INTO rule_threshold (camera_id, rule_key, rule_value)
SELECT NULL, 'analyze_fps', '8'
WHERE NOT EXISTS (
    SELECT 1 FROM rule_threshold WHERE camera_id IS NULL AND rule_key = 'analyze_fps'
);

INSERT INTO rule_threshold (camera_id, rule_key, rule_value)
SELECT NULL, 'alert_cooldown_sec', '30'
WHERE NOT EXISTS (
    SELECT 1 FROM rule_threshold WHERE camera_id IS NULL AND rule_key = 'alert_cooldown_sec'
);

INSERT INTO rule_threshold (camera_id, rule_key, rule_value)
SELECT NULL, 'allow_green_only', 'true'
WHERE NOT EXISTS (
    SELECT 1 FROM rule_threshold WHERE camera_id IS NULL AND rule_key = 'allow_green_only'
);

INSERT INTO rule_threshold (camera_id, rule_key, rule_value)
SELECT NULL, 'vehicle_conf', '0.35'
WHERE NOT EXISTS (
    SELECT 1 FROM rule_threshold WHERE camera_id IS NULL AND rule_key = 'vehicle_conf'
);

INSERT INTO rule_threshold (camera_id, rule_key, rule_value)
SELECT NULL, 'gun_conf', '0.35'
WHERE NOT EXISTS (
    SELECT 1 FROM rule_threshold WHERE camera_id IS NULL AND rule_key = 'gun_conf'
);

INSERT INTO rule_threshold (camera_id, rule_key, rule_value)
SELECT NULL, 'plate_conf', '0.25'
WHERE NOT EXISTS (
    SELECT 1 FROM rule_threshold WHERE camera_id IS NULL AND rule_key = 'plate_conf'
);
