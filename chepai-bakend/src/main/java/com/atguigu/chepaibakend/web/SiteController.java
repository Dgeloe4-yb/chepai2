package com.atguigu.chepaibakend.web;

import com.atguigu.chepaibakend.config.Auths;
import com.atguigu.chepaibakend.dto.SiteDtos;
import com.atguigu.chepaibakend.repository.SiteRepository;
import jakarta.servlet.http.HttpServletRequest;
import java.util.List;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/sites")
public class SiteController {

    private final SiteRepository sites;

    public SiteController(SiteRepository sites) {
        this.sites = sites;
    }

    @GetMapping
    public List<SiteDtos.SiteView> list(HttpServletRequest request) {
        Auths.requireSuperAdmin(request);
        return sites.listAll();
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public CreatedBody create(@RequestBody SiteDtos.SiteCreate body, HttpServletRequest request) {
        Auths.requireSuperAdmin(request);
        if (body.name() == null || body.name().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "name required");
        }
        long id = sites.insert(body.name(), body.address());
        return new CreatedBody(id);
    }

    public record CreatedBody(long id) {}
}
