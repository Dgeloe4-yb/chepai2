package com.atguigu.chepaibakend.dto;

import java.time.LocalDateTime;

public final class CameraDtos {
    private CameraDtos() {}

    public record CameraCreate(Long siteId, String name, String rtspUrl, Integer channelNo, String edgeBoxId) {}

    public record CameraUpdate(String name, String rtspUrl, Integer channelNo, String edgeBoxId) {}

    public record CameraView(
            Long id, Long siteId, String name, String rtspUrl, Integer channelNo, String edgeBoxId, LocalDateTime createdAt) {}
}
