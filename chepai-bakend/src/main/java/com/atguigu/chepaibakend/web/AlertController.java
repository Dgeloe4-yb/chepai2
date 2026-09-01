package com.atguigu.chepaibakend.web;

import com.atguigu.chepaibakend.config.AlertTypes;
import com.atguigu.chepaibakend.config.AuthPrincipal;
import com.atguigu.chepaibakend.config.Auths;
import com.atguigu.chepaibakend.config.BoxAccess;
import com.atguigu.chepaibakend.config.FeatureCatalog;
import com.atguigu.chepaibakend.dto.AlertDtos;
import com.atguigu.chepaibakend.repository.AlertRepository;
import com.atguigu.chepaibakend.repository.CameraRepository;
import com.atguigu.chepaibakend.repository.FeatureRepository;
import jakarta.servlet.http.HttpServletRequest;
import java.time.LocalDateTime;
import java.util.List;
import org.springframework.format.annotation.DateTimeFormat;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/alerts")
public class AlertController {

    private final AlertRepository alerts;
    private final CameraRepository cameras;
    private final BoxAccess boxAccess;
    private final FeatureRepository features;

    public AlertController(
            AlertRepository alerts,
            CameraRepository cameras,
            BoxAccess boxAccess,
            FeatureRepository features) {
        this.alerts = alerts;
        this.cameras = cameras;
        this.boxAccess = boxAccess;
        this.features = features;
    }

    @GetMapping
    public AlertDtos.PageResult<AlertDtos.AlertView> list(
            @RequestParam(required = false) Long cameraId,
            @RequestParam(required = false) String type,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME)
                    LocalDateTime from,
            @RequestParam(required = false) @DateTimeFormat(iso = DateTimeFormat.ISO.DATE_TIME)
                    LocalDateTime to,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size,
            HttpServletRequest request) {
        AuthPrincipal p = Auths.requireHuman(request);
        List<String> scoped = boxAccess.scopedBoxIds(p);
        if (cameraId != null) {
            var cam = cameras.findById(cameraId);
            if (cam == null) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND, "camera not found");
            }
            if (scoped != null
                    && (cam.edgeBoxId() == null || !scoped.contains(cam.edgeBoxId()))) {
                throw new ResponseStatusException(HttpStatus.FORBIDDEN, "camera not assigned");
            }
        }
        List<String> allowedTypes =
                p.isSuperAdmin() ? null : FeatureCatalog.expandForAlertQuery(features.listForUser(p.userId()));
        var pageResult = alerts.search(cameraId, type, from, to, page, size, scoped, allowedTypes);
        if (p.isSuperAdmin()) {
            return pageResult;
        }
        var hidden = pageResult.content().stream().map(AlertDtos.AlertView::hideSnapshot).toList();
        return new AlertDtos.PageResult<>(hidden, pageResult.total(), pageResult.page(), pageResult.size());
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public CreatedBody ingest(
            @RequestBody AlertDtos.AlertIngest body,
            @RequestHeader(value = "X-Idempotency-Key", required = false) String idempotencyHeader,
            HttpServletRequest request) {
        Auths.requireEdge(request);
        if (body.cameraId() == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "cameraId required");
        }
        if (body.alertType() == null || body.alertType().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "alertType required");
        }
        if (!AlertTypes.isIngest(body.alertType())) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST, "unsupported alertType: " + body.alertType());
        }
        String idempotencyKey =
                body.idempotencyKey() != null && !body.idempotencyKey().isBlank()
                        ? body.idempotencyKey()
                        : idempotencyHeader;
        long id =
                alerts.insert(
                        body.cameraId(),
                        body.alertType(),
                        body.score(),
                        body.snapshotPath(),
                        body.rawJson(),
                        idempotencyKey);
        return new CreatedBody(id);
    }

    public record CreatedBody(long id) {}
}
