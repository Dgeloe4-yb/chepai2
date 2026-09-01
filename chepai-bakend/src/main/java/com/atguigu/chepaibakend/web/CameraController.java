package com.atguigu.chepaibakend.web;

import com.atguigu.chepaibakend.config.AuthPrincipal;
import com.atguigu.chepaibakend.config.Auths;
import com.atguigu.chepaibakend.config.BoxAccess;
import com.atguigu.chepaibakend.dto.CameraDtos;
import com.atguigu.chepaibakend.repository.CameraRepository;
import com.atguigu.chepaibakend.repository.EdgeBoxRepository;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/cameras")
public class CameraController {

    private final CameraRepository cameras;
    private final EdgeBoxRepository boxes;
    private final BoxAccess boxAccess;

    public CameraController(CameraRepository cameras, EdgeBoxRepository boxes, BoxAccess boxAccess) {
        this.cameras = cameras;
        this.boxes = boxes;
        this.boxAccess = boxAccess;
    }

    @GetMapping
    public List<CameraDtos.CameraView> list(
            @RequestParam(required = false) Long siteId,
            @RequestParam(required = false) String edgeBoxId,
            HttpServletRequest request) {
        AuthPrincipal p = Auths.requireHuman(request);
        if (edgeBoxId != null && !edgeBoxId.isBlank()) {
            boxAccess.requireBox(p, edgeBoxId);
            return cameras.listByEdgeBoxId(edgeBoxId.trim());
        }
        if (!p.isSuperAdmin()) {
            return cameras.listByEdgeBoxIds(boxAccess.scopedBoxIds(p));
        }
        return cameras.listBySite(siteId);
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public CreatedBody create(@RequestBody CameraDtos.CameraCreate body, HttpServletRequest request) {
        Auths.requireSuperAdmin(request);
        if (body.siteId() == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "siteId required");
        }
        if (body.name() == null || body.name().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "name required");
        }
        ensureBox(body.edgeBoxId());
        long id = cameras.insert(body.siteId(), body.name(), body.rtspUrl(), body.channelNo(), body.edgeBoxId());
        return new CreatedBody(id);
    }

    @PutMapping("/{id}")
    public void update(
            @PathVariable long id, @RequestBody CameraDtos.CameraUpdate body, HttpServletRequest request) {
        Auths.requireSuperAdmin(request);
        if (body.name() == null || body.name().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "name required");
        }
        ensureBox(body.edgeBoxId());
        if (!cameras.update(id, body.name(), body.rtspUrl(), body.channelNo(), body.edgeBoxId())) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "camera not found");
        }
    }

    private void ensureBox(String edgeBoxId) {
        if (edgeBoxId == null || edgeBoxId.isBlank()) {
            return;
        }
        String id = edgeBoxId.trim();
        if (boxes.findById(id) == null) {
            boxes.upsert(id, id);
        }
    }

    public record CreatedBody(long id) {}
}
