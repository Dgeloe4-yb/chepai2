package com.atguigu.chepaibakend.dto;

import java.util.List;
import java.util.Map;

public final class EdgeDtos {

    private EdgeDtos() {}

    public record EdgeConfigView(
            String edgeBoxId,
            List<CameraWithRois> cameras,
            Map<String, String> rules) {}

    public record CameraWithRois(
            long id,
            long siteId,
            String name,
            String rtspUrl,
            Integer channelNo,
            List<RoiDtos.RoiView> rois,
            Map<String, String> rules) {}

    public record RuleView(String ruleKey, String ruleValue, Long cameraId) {}

    public record HeartbeatRequest(
            String edgeBoxId,
            String hostname,
            String agentVersion,
            Integer cameraCount,
            Map<String, Object> status) {}

    public record LogUploadRequest(String edgeBoxId, String source, String body, java.time.LocalDateTime collectedAt) {}

    public record EdgeLogView(
            Long id,
            String edgeBoxId,
            String source,
            String body,
            java.time.LocalDateTime collectedAt,
            java.time.LocalDateTime createdAt) {}
}
