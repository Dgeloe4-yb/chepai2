package com.atguigu.chepaibakend.dto;

import com.fasterxml.jackson.databind.JsonNode;
import java.time.LocalDateTime;

public final class AlertDtos {
    private AlertDtos() {}

    public record AlertIngest(
            Long cameraId,
            String alertType,
            Double score,
            String snapshotPath,
            JsonNode rawJson,
            String idempotencyKey) {}

    public record AlertView(
            Long id,
            Long cameraId,
            String alertType,
            Double score,
            String snapshotPath,
            JsonNode rawJson,
            LocalDateTime createdAt) {
        public AlertView hideSnapshot() {
            return new AlertView(id, cameraId, alertType, score, null, null, createdAt);
        }
    }

    public record PageResult<T>(java.util.List<T> content, long total, int page, int size) {}
}
