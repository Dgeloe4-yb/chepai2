package com.atguigu.chepaibakend.dto;

import java.time.LocalDateTime;

public final class RoiDtos {
    private RoiDtos() {}

    public record RoiCreate(Long cameraId, String regionType, String name, String polygonJson) {}

    public record RoiView(Long id, Long cameraId, String regionType, String name, String polygonJson, LocalDateTime createdAt) {}
}
