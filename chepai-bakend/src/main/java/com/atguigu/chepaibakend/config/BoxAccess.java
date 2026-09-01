package com.atguigu.chepaibakend.config;

import com.atguigu.chepaibakend.repository.EdgeBoxRepository;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

@Component
public class BoxAccess {

    private final EdgeBoxRepository boxes;

    public BoxAccess(EdgeBoxRepository boxes) {
        this.boxes = boxes;
    }

    /** null = all boxes (super admin). */
    public List<String> scopedBoxIds(AuthPrincipal principal) {
        if (principal.isSuperAdmin()) {
            return null;
        }
        return boxes.listIdsForUser(principal.userId());
    }

    public void requireBox(AuthPrincipal principal, String edgeBoxId) {
        if (edgeBoxId == null || edgeBoxId.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "edgeBoxId required");
        }
        String id = edgeBoxId.trim();
        if (boxes.findById(id) == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "edge box not found");
        }
        if (principal.isSuperAdmin()) {
            return;
        }
        if (!boxes.userOwns(principal.userId(), id)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "edge box not assigned");
        }
    }
}
