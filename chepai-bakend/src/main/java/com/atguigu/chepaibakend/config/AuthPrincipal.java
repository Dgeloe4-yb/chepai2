package com.atguigu.chepaibakend.config;

public record AuthPrincipal(Long userId, String username, String role, boolean edge) {

    public static AuthPrincipal forEdge() {
        return new AuthPrincipal(null, "edge", "EDGE", true);
    }

    public boolean isSuperAdmin() {
        return !edge && "SUPER_ADMIN".equals(role);
    }

    public boolean isUser() {
        return !edge && "USER".equals(role);
    }

    public boolean isHuman() {
        return !edge && userId != null;
    }
}
