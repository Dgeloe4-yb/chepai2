package com.atguigu.chepaibakend.web;

import com.atguigu.chepaibakend.config.Auths;
import com.atguigu.chepaibakend.dto.CameraDtos;
import com.atguigu.chepaibakend.dto.EdgeDtos;
import com.atguigu.chepaibakend.dto.RoiDtos;
import com.atguigu.chepaibakend.repository.CameraRepository;
import com.atguigu.chepaibakend.repository.RoiRepository;
import com.atguigu.chepaibakend.repository.RuleThresholdRepository;
import jakarta.servlet.http.HttpServletRequest;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/edge")
public class EdgeConfigController {

    private final CameraRepository cameras;
    private final RoiRepository rois;
    private final RuleThresholdRepository rules;

    public EdgeConfigController(
            CameraRepository cameras, RoiRepository rois, RuleThresholdRepository rules) {
        this.cameras = cameras;
        this.rois = rois;
        this.rules = rules;
    }

    @GetMapping("/config")
    public EdgeDtos.EdgeConfigView config(
            @RequestParam String edgeBoxId,
            HttpServletRequest request) {
        Auths.requireEdge(request);
        if (edgeBoxId == null || edgeBoxId.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "edgeBoxId required");
        }
        List<CameraDtos.CameraView> cams = cameras.listByEdgeBoxId(edgeBoxId.trim());
        List<EdgeDtos.CameraWithRois> withRois = new ArrayList<>();
        for (CameraDtos.CameraView cam : cams) {
            List<RoiDtos.RoiView> roiList = rois.listByCamera(cam.id());
            Map<String, String> camRules = rules.resolveRules(cam.id());
            withRois.add(new EdgeDtos.CameraWithRois(
                    cam.id(), cam.siteId(), cam.name(), cam.rtspUrl(), cam.channelNo(), roiList, camRules));
        }
        Map<String, String> mergedRules = rules.resolveRules(null);
        return new EdgeDtos.EdgeConfigView(edgeBoxId.trim(), withRois, mergedRules);
    }
}
