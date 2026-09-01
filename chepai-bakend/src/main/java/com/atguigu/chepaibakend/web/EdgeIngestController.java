package com.atguigu.chepaibakend.web;

import com.atguigu.chepaibakend.config.Auths;
import com.atguigu.chepaibakend.dto.EdgeDtos;
import com.atguigu.chepaibakend.repository.EdgeBoxRepository;
import com.atguigu.chepaibakend.repository.EdgeLogRepository;
import com.atguigu.chepaibakend.repository.FeatureRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/edge")
public class EdgeIngestController {

    private final EdgeBoxRepository boxes;
    private final EdgeLogRepository logs;
    private final FeatureRepository features;
    private final ObjectMapper objectMapper;
    private final int logMaxChars;

    public EdgeIngestController(
            EdgeBoxRepository boxes,
            EdgeLogRepository logs,
            FeatureRepository features,
            ObjectMapper objectMapper,
            @Value("${chepai.edge.log-max-chars:200000}") int logMaxChars) {
        this.boxes = boxes;
        this.logs = logs;
        this.features = features;
        this.objectMapper = objectMapper;
        this.logMaxChars = Math.max(4_000, logMaxChars);
    }

    @PostMapping("/heartbeat")
    public Map<String, Object> heartbeat(@RequestBody EdgeDtos.HeartbeatRequest body, HttpServletRequest request) {
        Auths.requireEdge(request);
        String id = requireBoxId(body == null ? null : body.edgeBoxId());
        String hostname = trimToNull(body.hostname());
        String name = hostname == null ? id : hostname;
        String statusJson = null;
        if (body.status() != null) {
            try {
                statusJson = objectMapper.writeValueAsString(body.status());
            } catch (JsonProcessingException ex) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "invalid status");
            }
        }
        boxes.touchHeartbeat(id, name, hostname, trimToNull(body.agentVersion()), body.cameraCount(), statusJson);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", id);
        out.put("status", "ok");
        out.put("features", features.listForBox(id));
        return out;
    }

    @PostMapping("/logs")
    public Map<String, String> uploadLogs(@RequestBody EdgeDtos.LogUploadRequest body, HttpServletRequest request) {
        Auths.requireEdge(request);
        if (body == null || body.body() == null || body.body().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "body required");
        }
        String id = requireBoxId(body.edgeBoxId());
        if (boxes.findById(id) == null) {
            boxes.touchHeartbeat(id, id, null, null, null, null);
        }
        String source = trimToNull(body.source());
        if (source == null) {
            source = "journal";
        }
        if (source.length() > 32) {
            source = source.substring(0, 32);
        }
        String text = body.body();
        if (text.length() > logMaxChars) {
            text = text.substring(text.length() - logMaxChars);
        }
        logs.insert(id, source, text, body.collectedAt());
        return Map.of("id", id, "status", "ok");
    }

    static String requireBoxId(String raw) {
        if (raw == null || raw.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "edgeBoxId required");
        }
        String id = raw.trim();
        if (!id.matches("[A-Za-z0-9._-]{1,64}")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "invalid edge box id");
        }
        return id;
    }

    private static String trimToNull(String v) {
        if (v == null) {
            return null;
        }
        String t = v.trim();
        return t.isEmpty() ? null : t;
    }
}
