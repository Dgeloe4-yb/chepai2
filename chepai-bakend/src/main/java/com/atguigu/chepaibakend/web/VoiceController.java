package com.atguigu.chepaibakend.web;

import com.atguigu.chepaibakend.config.AlertTypes;
import com.atguigu.chepaibakend.config.AuthPrincipal;
import com.atguigu.chepaibakend.config.Auths;
import com.atguigu.chepaibakend.config.BoxAccess;
import com.atguigu.chepaibakend.dto.AuthDtos;
import com.atguigu.chepaibakend.repository.FeatureRepository;
import com.atguigu.chepaibakend.repository.VoiceClipRepository;
import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.io.FileSystemResource;
import org.springframework.core.io.Resource;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

@RestController
public class VoiceController {

    private final Path voiceDir;
    private final VoiceClipRepository clips;
    private final BoxAccess boxAccess;
    private final FeatureRepository features;

    public VoiceController(
            @Value("${chepai.voice.dir:./data/voice}") String voiceDir,
            VoiceClipRepository clips,
            BoxAccess boxAccess,
            FeatureRepository features)
            throws IOException {
        this.voiceDir = Path.of(voiceDir).toAbsolutePath().normalize();
        this.clips = clips;
        this.boxAccess = boxAccess;
        this.features = features;
        Files.createDirectories(this.voiceDir);
    }

    @GetMapping("/api/voice")
    public List<AuthDtos.VoiceClipView> list(
            @RequestParam String edgeBoxId, HttpServletRequest request) {
        AuthPrincipal p = Auths.requireHuman(request);
        boxAccess.requireBox(p, edgeBoxId);
        return clips.listByBox(edgeBoxId.trim());
    }

    @PostMapping(value = "/api/voice", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public AuthDtos.VoiceClipView upload(
            @RequestParam String edgeBoxId,
            @RequestParam String alertType,
            @RequestParam("file") MultipartFile file,
            HttpServletRequest request)
            throws IOException {
        AuthPrincipal p = Auths.requireHuman(request);
        boxAccess.requireBox(p, edgeBoxId);
        if (!AlertTypes.isVoice(alertType)) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST, "alertType must be one of " + AlertTypes.VOICE);
        }
        if (!p.isSuperAdmin() && (p.userId() == null || !features.userHas(p.userId(), alertType))) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "feature not granted: " + alertType);
        }
        if (file == null || file.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "file required");
        }
        byte[] bytes = file.getBytes();
        if (!isWav(bytes)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "only PCM WAV is supported");
        }
        String boxId = edgeBoxId.trim();
        Path dir = safeBoxDir(boxId);
        Files.createDirectories(dir);
        String stored = alertType + ".wav";
        Path target = dir.resolve(stored).normalize();
        if (!target.startsWith(dir)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "invalid path");
        }
        Files.write(target, bytes);
        String sha = sha256(bytes);
        String original = file.getOriginalFilename();
        clips.upsert(boxId, alertType, original, stored, sha);
        return clips.listByBox(boxId).stream()
                .filter(v -> alertType.equals(v.alertType()))
                .findFirst()
                .orElseThrow();
    }

    @GetMapping("/api/voice/file/{edgeBoxId}/{alertType}")
    public ResponseEntity<Resource> downloadHuman(
            @PathVariable String edgeBoxId, @PathVariable String alertType, HttpServletRequest request) {
        AuthPrincipal p = Auths.requireHuman(request);
        boxAccess.requireBox(p, edgeBoxId);
        return fileResponse(edgeBoxId, alertType);
    }

    @GetMapping("/api/edge/voice")
    public AuthDtos.EdgeVoiceManifest edgeManifest(
            @RequestParam String edgeBoxId, HttpServletRequest request) {
        Auths.requireEdge(request);
        if (edgeBoxId == null || edgeBoxId.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "edgeBoxId required");
        }
        String boxId = edgeBoxId.trim();
        List<AuthDtos.EdgeVoiceClip> items = new ArrayList<>();
        for (var clip : clips.listByBox(boxId)) {
            items.add(
                    new AuthDtos.EdgeVoiceClip(
                            clip.alertType(),
                            clip.sha256(),
                            "/api/edge/voice/" + boxId + "/" + clip.alertType(),
                            clip.updatedAt()));
        }
        return new AuthDtos.EdgeVoiceManifest(boxId, items);
    }

    @GetMapping("/api/edge/voice/{edgeBoxId}/{alertType}")
    public ResponseEntity<Resource> downloadEdge(
            @PathVariable String edgeBoxId, @PathVariable String alertType, HttpServletRequest request) {
        Auths.requireEdge(request);
        return fileResponse(edgeBoxId, alertType);
    }

    private ResponseEntity<Resource> fileResponse(String edgeBoxId, String alertType) {
        var row = clips.find(edgeBoxId, alertType);
        if (row == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "voice clip not found");
        }
        Path file = safeBoxDir(edgeBoxId).resolve(row.storedName()).normalize();
        if (!file.startsWith(voiceDir) || !Files.isRegularFile(file)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "voice file missing");
        }
        Resource body = new FileSystemResource(file);
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_TYPE, "audio/wav")
                .header(HttpHeaders.CACHE_CONTROL, "no-store")
                .body(body);
    }

    private Path safeBoxDir(String edgeBoxId) {
        if (!edgeBoxId.matches("[A-Za-z0-9._-]{1,64}")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "invalid edge box id");
        }
        return voiceDir.resolve(edgeBoxId).normalize();
    }

    private static boolean isWav(byte[] bytes) {
        if (bytes == null || bytes.length < 12) {
            return false;
        }
        return bytes[0] == 'R'
                && bytes[1] == 'I'
                && bytes[2] == 'F'
                && bytes[3] == 'F'
                && bytes[8] == 'W'
                && bytes[9] == 'A'
                && bytes[10] == 'V'
                && bytes[11] == 'E';
    }

    private static String sha256(byte[] bytes) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(md.digest(bytes));
        } catch (NoSuchAlgorithmException ex) {
            throw new IllegalStateException(ex);
        }
    }
}
