package com.atguigu.chepaibakend.dto;

import java.time.LocalDateTime;

public final class SiteDtos {
    private SiteDtos() {}

    public record SiteCreate(String name, String address) {}

    public record SiteView(Long id, String name, String address, LocalDateTime createdAt) {}
}
