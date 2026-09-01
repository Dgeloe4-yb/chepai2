package com.atguigu.chepaibakend.config;

import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Component;

@Component
public class PasswordHasher {
    private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();

    public String hash(String raw) {
        return encoder.encode(raw);
    }

    public boolean matches(String raw, String hashed) {
        if (raw == null || hashed == null || hashed.isBlank()) {
            return false;
        }
        return encoder.matches(raw, hashed);
    }
}
