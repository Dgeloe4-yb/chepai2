package com.atguigu.chepaibakend.web;

import com.atguigu.chepaibakend.config.AuthPrincipal;
import com.atguigu.chepaibakend.config.Auths;
import com.atguigu.chepaibakend.config.BoxAccess;
import com.atguigu.chepaibakend.dto.AuthDtos;
import com.atguigu.chepaibakend.dto.EdgeDtos;
import com.atguigu.chepaibakend.repository.EdgeBoxRepository;
import com.atguigu.chepaibakend.repository.EdgeLogRepository;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/edge-boxes")
public class EdgeBoxController {

    private final EdgeBoxRepository boxes;
    private final EdgeLogRepository logs;
    private final BoxAccess boxAccess;

    public EdgeBoxController(EdgeBoxRepository boxes, EdgeLogRepository logs, BoxAccess boxAccess) {
        this.boxes = boxes;
        this.logs = logs;
        this.boxAccess = boxAccess;
    }

    @GetMapping
    public List<AuthDtos.EdgeBoxView> list(HttpServletRequest request) {
        AuthPrincipal p = Auths.requireHuman(request);
        if (p.isSuperAdmin()) {
            return boxes.listAll();
        }
        return boxes.listForUser(p.userId());
    }

    @GetMapping("/{id}/logs")
    public List<EdgeDtos.EdgeLogView> logs(
            @PathVariable String id,
            @RequestParam(defaultValue = "10") int limit,
            HttpServletRequest request) {
        AuthPrincipal p = Auths.requireHuman(request);
        boxAccess.requireBox(p, id);
        return logs.listByBox(id.trim(), limit);
    }
}
