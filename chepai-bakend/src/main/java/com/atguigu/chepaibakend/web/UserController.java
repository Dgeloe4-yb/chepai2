package com.atguigu.chepaibakend.web;

import com.atguigu.chepaibakend.config.Auths;
import com.atguigu.chepaibakend.config.FeatureCatalog;
import com.atguigu.chepaibakend.config.PasswordHasher;
import com.atguigu.chepaibakend.dto.AuthDtos;
import com.atguigu.chepaibakend.repository.EdgeBoxRepository;
import com.atguigu.chepaibakend.repository.FeatureRepository;
import com.atguigu.chepaibakend.repository.UserRepository;
import jakarta.servlet.http.HttpServletRequest;
import java.util.ArrayList;
import java.util.List;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/users")
public class UserController {

    private final UserRepository users;
    private final EdgeBoxRepository boxes;
    private final FeatureRepository features;
    private final PasswordHasher passwords;

    public UserController(
            UserRepository users,
            EdgeBoxRepository boxes,
            FeatureRepository features,
            PasswordHasher passwords) {
        this.users = users;
        this.boxes = boxes;
        this.features = features;
        this.passwords = passwords;
    }

    @GetMapping
    public List<AuthDtos.UserView> list(HttpServletRequest request) {
        Auths.requireSuperAdmin(request);
        List<AuthDtos.UserView> rows = new ArrayList<>();
        for (var v : users.listAll()) {
            rows.add(v.withFeatures(features.listForUser(v.id())));
        }
        return rows;
    }

    @PostMapping
    @ResponseStatus(HttpStatus.CREATED)
    public CreatedUser create(@RequestBody AuthDtos.UserCreate body, HttpServletRequest request) {
        Auths.requireSuperAdmin(request);
        if (body.username() == null || body.username().isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "username required");
        }
        if (body.password() == null || body.password().length() < 6) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "password must be at least 6 characters");
        }
        String role = body.role() == null || body.role().isBlank() ? "USER" : body.role().trim();
        if (!role.equals("USER") && !role.equals("SUPER_ADMIN")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "role must be USER or SUPER_ADMIN");
        }
        try {
            long id =
                    users.insert(
                            body.username().trim(),
                            passwords.hash(body.password()),
                            body.displayName(),
                            role);
            if (role.equals("USER")) {
                features.grantAll(id);
            }
            return new CreatedUser(id);
        } catch (DuplicateKeyException ex) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "username already exists");
        }
    }

    @PutMapping("/{id}")
    public void update(@PathVariable long id, @RequestBody AuthDtos.UserUpdate body, HttpServletRequest request) {
        Auths.requireSuperAdmin(request);
        String hash = null;
        if (body.password() != null && !body.password().isBlank()) {
            if (body.password().length() < 6) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "password must be at least 6 characters");
            }
            hash = passwords.hash(body.password());
        }
        if (!users.update(id, body.displayName(), hash, body.enabled())) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "user not found");
        }
    }

    @GetMapping("/{id}/edge-boxes")
    public List<AuthDtos.EdgeBoxView> assigned(@PathVariable long id, HttpServletRequest request) {
        Auths.requireSuperAdmin(request);
        if (users.findById(id) == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "user not found");
        }
        return boxes.listForUser(id);
    }

    @PutMapping("/{id}/edge-boxes")
    public void assign(
            @PathVariable long id, @RequestBody AuthDtos.AssignBoxesRequest body, HttpServletRequest request) {
        Auths.requireSuperAdmin(request);
        if (users.findById(id) == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "user not found");
        }
        List<String> ids = body.edgeBoxIds() == null ? List.of() : body.edgeBoxIds();
        for (String boxId : ids) {
            if (boxId == null || boxId.isBlank() || boxes.findById(boxId.trim()) == null) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "unknown edge box: " + boxId);
            }
        }
        boxes.replaceUserBoxes(id, ids);
    }

    @GetMapping("/{id}/features")
    public List<String> features(@PathVariable long id, HttpServletRequest request) {
        Auths.requireSuperAdmin(request);
        if (users.findById(id) == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "user not found");
        }
        return features.listForUser(id);
    }

    @PutMapping("/{id}/features")
    public void assignFeatures(
            @PathVariable long id, @RequestBody AuthDtos.AssignFeaturesRequest body, HttpServletRequest request) {
        Auths.requireSuperAdmin(request);
        var user = users.findById(id);
        if (user == null) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "user not found");
        }
        if (!"USER".equals(user.role())) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "only USER accounts have features");
        }
        List<String> keys = body.features() == null ? List.of() : body.features();
        for (String key : keys) {
            if (key == null || key.isBlank() || !FeatureCatalog.isKnown(key.trim())) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "unknown feature: " + key);
            }
        }
        features.replaceForUser(id, keys);
    }

    public record CreatedUser(long id) {}
}
