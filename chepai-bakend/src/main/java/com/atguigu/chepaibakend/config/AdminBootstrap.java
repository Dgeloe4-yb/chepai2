package com.atguigu.chepaibakend.config;

import com.atguigu.chepaibakend.repository.CameraRepository;
import com.atguigu.chepaibakend.repository.EdgeBoxRepository;
import com.atguigu.chepaibakend.repository.UserRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

@Component
public class AdminBootstrap implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(AdminBootstrap.class);

    private final UserRepository users;
    private final PasswordHasher passwords;
    private final CameraRepository cameras;
    private final EdgeBoxRepository boxes;
    private final String adminUsername;
    private final String adminPassword;

    public AdminBootstrap(
            UserRepository users,
            PasswordHasher passwords,
            CameraRepository cameras,
            EdgeBoxRepository boxes,
            @Value("${chepai.admin.username:admin}") String adminUsername,
            @Value("${chepai.admin.password:ChepaiAdmin@2026}") String adminPassword) {
        this.users = users;
        this.passwords = passwords;
        this.cameras = cameras;
        this.boxes = boxes;
        this.adminUsername = adminUsername;
        this.adminPassword = adminPassword;
    }

    @Override
    public void run(ApplicationArguments args) {
        for (var cam : cameras.listBySite(null)) {
            if (cam.edgeBoxId() != null && !cam.edgeBoxId().isBlank()) {
                String id = cam.edgeBoxId().trim();
                if (boxes.findById(id) == null) {
                    boxes.upsert(id, id);
                }
            }
        }
        if (users.count() > 0) {
            return;
        }
        String username = adminUsername == null || adminUsername.isBlank() ? "admin" : adminUsername.trim();
        String password =
                adminPassword == null || adminPassword.isBlank() ? "ChepaiAdmin@2026" : adminPassword;
        users.insert(username, passwords.hash(password), "超级管理员", "SUPER_ADMIN");
        log.info("bootstrapped super admin username={}", username);
    }
}
