-- Idempotency key for edge alert deduplication (MySQL 8+)
ALTER TABLE alert_event
    ADD COLUMN idempotency_key VARCHAR(128) NULL AFTER raw_json;

CREATE UNIQUE INDEX uk_alert_idempotency ON alert_event (idempotency_key);
