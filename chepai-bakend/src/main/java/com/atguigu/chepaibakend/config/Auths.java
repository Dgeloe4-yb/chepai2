package com.atguigu.chepaibakend.config;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;

public final class Auths {
    public static final String ATTR = "chepai.auth";

    private Auths() {}

    public static AuthPrincipal get(HttpServletRequest request) {
        Object v = request.getAttribute(ATTR);
        return v instanceof AuthPrincipal p ? p : null;
    }

    public static AuthPrincipal requireHuman(HttpServletRequest request) {
        AuthPrincipal p = get(request);
        if (p == null || !p.isHuman()) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "login required");
        }
        return p;
    }

    public static AuthPrincipal requireSuperAdmin(HttpServletRequest request) {
        AuthPrincipal p = requireHuman(request);
        if (!p.isSuperAdmin()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "super admin only");
        }
        return p;
    }

    public static AuthPrincipal requireEdge(HttpServletRequest request) {
        AuthPrincipal p = get(request);
        if (p == null || !p.edge()) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "edge token required");
        }
        return p;
    }
}
