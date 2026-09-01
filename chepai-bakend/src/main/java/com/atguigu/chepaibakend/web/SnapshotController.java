package com.atguigu.chepaibakend.web;

import com.atguigu.chepaibakend.config.Auths;
import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;
import java.util.UUID;
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
@RequestMapping("/api/snapshots")
public class SnapshotController {

    private final Path snapshotDir;

    public SnapshotController(@Value("${chepai.snapshots.dir:./data/snapshots}") String snapshotDir)
            throws IOException {
        this.snapshotDir = Path.of(snapshotDir).toAbsolutePath().normalize();
        Files.createDirectories(this.snapshotDir);
    }

    @PostMapping(consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public Map<String, String> upload(
            @RequestParam("file") MultipartFile file, HttpServletRequest request)
            throws IOException {
        Auths.requireEdge(request);
        if (file.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "file required");
        }
        String safeName = UUID.randomUUID() + ".jpg";
        Path target = snapshotDir.resolve(safeName).normalize();
        if (!target.startsWith(snapshotDir)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "invalid path");
        }
        file.transferTo(target);
        return Map.of("snapshotPath", "/api/snapshots/" + safeName);
    }

    @GetMapping("/{filename}")
    public ResponseEntity<Resource> download(@PathVariable String filename, HttpServletRequest request) {
        Auths.requireSuperAdmin(request);
        if (!filename.matches("[a-f0-9\\-]+\\.jpg")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "invalid filename");
        }
        Path file = snapshotDir.resolve(filename).normalize();
        if (!file.startsWith(snapshotDir) || !Files.isRegularFile(file)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "snapshot not found");
        }
        Resource body = new FileSystemResource(file);
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_TYPE, MediaType.IMAGE_JPEG_VALUE)
                .header(HttpHeaders.CACHE_CONTROL, "public, max-age=3600")
                .body(body);
    }
}
