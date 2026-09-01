package com.atguigu.chepaibakend.config;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

@Component
public class EdgeAuth {

    private final String edgeToken;

    public EdgeAuth(@Value("${chepai.edge.token:}") String edgeToken) {
        this.edgeToken = edgeToken == null ? "" : edgeToken.trim();
    }

    public void requireEdgeToken(String provided) {
        if (edgeToken.isEmpty()) {
            return;
        }
        if (provided == null || !edgeToken.equals(provided.trim())) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "invalid or missing X-Chepai-Edge-Token");
        }
    }
}
