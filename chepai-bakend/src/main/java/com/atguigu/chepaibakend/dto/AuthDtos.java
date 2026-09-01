package com.atguigu.chepaibakend.dto;

import java.time.LocalDateTime;
import java.util.List;

public final class AuthDtos {
    private AuthDtos() {}

    public record LoginRequest(String username, String password) {}

    public record UserView(
            Long id,
            String username,
            String displayName,
            String role,
            boolean enabled,
            LocalDateTime createdAt,
            List<String> features) {
        public UserView withFeatures(List<String> keys) {
            return new UserView(
                    id, username, displayName, role, enabled, createdAt, keys == null ? List.of() : List.copyOf(keys));
        }
    }

    public record LoginResponse(String token, UserView user) {}

    public record UserCreate(String username, String password, String displayName, String role) {}

    public record UserUpdate(String displayName, String password, Boolean enabled) {}

    public record EdgeBoxView(
            String id,
            String name,
            LocalDateTime createdAt,
            LocalDateTime lastSeenAt,
            String hostname,
            String agentVersion,
            Integer cameraCount,
            boolean online,
            com.fasterxml.jackson.databind.JsonNode status) {}

    public record EdgeBoxCreate(String id, String name) {}

    public record AssignBoxesRequest(List<String> edgeBoxIds) {}

    public record AssignFeaturesRequest(List<String> features) {}

    public record VoiceClipView(String edgeBoxId, String alertType, String originalName, String sha256, LocalDateTime updatedAt) {}

    public record EdgeVoiceManifest(String edgeBoxId, List<EdgeVoiceClip> clips) {}

    public record EdgeVoiceClip(String alertType, String sha256, String url, LocalDateTime updatedAt) {}
}
