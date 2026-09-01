package com.atguigu.chepaibakend.web;

import com.atguigu.chepaibakend.config.Auths;
import com.atguigu.chepaibakend.dto.RoiDtos;
import com.atguigu.chepaibakend.repository.RoiRepository;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/rois")
public class RoiController {

    private final RoiRepository rois;

    public RoiController(RoiRepository rois) {
        this.rois = rois;
    }

    @GetMapping
    public List<RoiDtos.RoiView> list(@RequestParam long cameraId, HttpServletRequest request) {
        Auths.requireSuperAdmin(request);
        return rois.listByCamera(cameraId);
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public CreatedBody create(@RequestBody RoiDtos.RoiCreate body, HttpServletRequest request) {
        Auths.requireSuperAdmin(request);
        if (body.cameraId() == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "cameraId required");
        }
        if (body.regionType() == null || body.regionType().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "regionType required");
        }
        if (body.polygonJson() == null || body.polygonJson().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "polygonJson required");
        }
        long id = rois.insert(body.cameraId(), body.regionType(), body.name(), body.polygonJson());
        return new CreatedBody(id);
    }

    @DeleteMapping("/{id}")
    @ResponseStatus(HttpStatus.NO_CONTENT)
    public void delete(@PathVariable long id, HttpServletRequest request) {
        Auths.requireSuperAdmin(request);
        if (!rois.delete(id)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "roi not found");
        }
    }

    public record CreatedBody(long id) {}
}
