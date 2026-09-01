package com.atguigu.chepaibakend.web;

import com.atguigu.chepaibakend.config.AuthPrincipal;
import com.atguigu.chepaibakend.config.Auths;
import com.atguigu.chepaibakend.config.FeatureCatalog;
import com.atguigu.chepaibakend.config.PasswordHasher;
import com.atguigu.chepaibakend.dto.AuthDtos;
import com.atguigu.chepaibakend.repository.FeatureRepository;
import com.atguigu.chepaibakend.repository.SessionRepository;
import com.atguigu.chepaibakend.repository.UserRepository;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final UserRepository users;
    private final SessionRepository sessions;
    private final FeatureRepository features;
    private final PasswordHasher passwords;
    private final int sessionDays;

    public AuthController(
            UserRepository users,
            SessionRepository sessions,
            FeatureRepository features,
            PasswordHasher passwords,
            @Value("${chepai.session.days:7}") int sessionDays) {
        this.users = users;
        this.sessions = sessions;
        this.features = features;
        this.passwords = passwords;
        this.sessionDays = sessionDays;
    }

    @PostMapping("/login")
    public AuthDtos.LoginResponse login(@RequestBody AuthDtos.LoginRequest body) {
        if (body.username() == null || body.password() == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "username and password required");
        }
        var user = users.findByUsername(body.username().trim());
        if (user == null || !user.enabled() || !passwords.matches(body.password(), user.passwordHash())) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "用户名或密码错误");
        }
        String token = sessions.create(user.id(), sessionDays);
        var view = users.viewById(user.id());
        return new AuthDtos.LoginResponse(token, attachFeatures(view));
    }

    @GetMapping("/me")
    public AuthDtos.UserView me(HttpServletRequest request) {
        AuthPrincipal p = Auths.requireHuman(request);
        var view = users.viewById(p.userId());
        if (view == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "user not found");
        }
        return attachFeatures(view);
    }

    @PostMapping("/logout")
    public void logout(HttpServletRequest request) {
        Auths.requireHuman(request);
        String h = request.getHeader("Authorization");
        if (h != null && h.regionMatches(true, 0, "Bearer ", 0, 7)) {
            sessions.delete(h.substring(7).trim());
        }
    }

    private AuthDtos.UserView attachFeatures(AuthDtos.UserView view) {
        if (view == null) {
            return null;
        }
        if ("SUPER_ADMIN".equals(view.role())) {
            return view.withFeatures(FeatureCatalog.ALL);
        }
        return view.withFeatures(features.listForUser(view.id()));
    }
}
