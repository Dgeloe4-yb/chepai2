package com.atguigu.chepaibakend.config;

import com.atguigu.chepaibakend.repository.SessionRepository;
import com.atguigu.chepaibakend.repository.UserRepository;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 20)
public class AuthFilter extends OncePerRequestFilter {

    private final EdgeAuth edgeAuth;
    private final SessionRepository sessions;
    private final UserRepository users;

    public AuthFilter(EdgeAuth edgeAuth, SessionRepository sessions, UserRepository users) {
        this.edgeAuth = edgeAuth;
        this.sessions = sessions;
        this.users = users;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        if (HttpMethod.OPTIONS.matches(request.getMethod())) {
            return true;
        }
        String path = pathOf(request);
        return "/api/health".equals(path) || "/api/auth/login".equals(path);
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        String bearer = bearerToken(request);
        if (bearer == null || bearer.isBlank()) {
            String q = request.getParameter("access_token");
            if (q != null && !q.isBlank()) {
                bearer = q.trim();
            }
        }
        if (bearer != null) {
            var session = sessions.findValid(bearer);
            if (session != null) {
                var user = users.findById(session.userId());
                if (user != null && user.enabled()) {
                    request.setAttribute(
                            Auths.ATTR, new AuthPrincipal(user.id(), user.username(), user.role(), false));
                    filterChain.doFilter(request, response);
                    return;
                }
            }
            unauthorized(response, "invalid or expired session");
            return;
        }

        String edgeToken = request.getHeader("X-Chepai-Edge-Token");
        if (edgeToken != null && !edgeToken.isBlank()) {
            try {
                edgeAuth.requireEdgeToken(edgeToken);
            } catch (Exception ex) {
                unauthorized(response, "invalid or missing X-Chepai-Edge-Token");
                return;
            }
            request.setAttribute(Auths.ATTR, AuthPrincipal.forEdge());
            filterChain.doFilter(request, response);
            return;
        }

        unauthorized(response, "login required");
    }

    private static String pathOf(HttpServletRequest request) {
        String uri = request.getRequestURI();
        String ctx = request.getContextPath();
        if (ctx != null && !ctx.isEmpty() && uri.startsWith(ctx)) {
            return uri.substring(ctx.length());
        }
        return uri;
    }

    private static String bearerToken(HttpServletRequest request) {
        String h = request.getHeader("Authorization");
        if (h == null) {
            return null;
        }
        String t = h.trim();
        if (t.length() > 7 && t.regionMatches(true, 0, "Bearer ", 0, 7)) {
            return t.substring(7).trim();
        }
        return null;
    }

    private static void unauthorized(HttpServletResponse response, String message) throws IOException {
        response.setStatus(HttpServletResponse.SC_UNAUTHORIZED);
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding("UTF-8");
        String safe = message.replace("\\", "\\\\").replace("\"", "\\\"");
        response.getWriter().write("{\"error\":\"" + safe + "\"}");
    }
}
