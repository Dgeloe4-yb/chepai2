package com.atguigu.chepaibakend.config;

import com.atguigu.chepaibakend.repository.AlertRepository;
import com.atguigu.chepaibakend.repository.EdgeLogRepository;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
public class DataRetentionJob {

    private static final Logger log = LoggerFactory.getLogger(DataRetentionJob.class);
    private static final Pattern SNAPSHOT_NAME = Pattern.compile("/api/snapshots/([a-f0-9\\-]+\\.jpg)");

    private final AlertRepository alerts;
    private final EdgeLogRepository edgeLogs;
    private final Path snapshotDir;
    private final int alertRetentionDays;
    private final int snapshotRetentionDays;
    private final int logRetentionDays;

    public DataRetentionJob(
            AlertRepository alerts,
            EdgeLogRepository edgeLogs,
            @Value("${chepai.snapshots.dir:./data/snapshots}") String snapshotDir,
            @Value("${chepai.retention.alert-days:30}") int alertRetentionDays,
            @Value("${chepai.retention.snapshot-days:30}") int snapshotRetentionDays,
            @Value("${chepai.retention.log-days:7}") int logRetentionDays)
            throws IOException {
        this.alerts = alerts;
        this.edgeLogs = edgeLogs;
        this.snapshotDir = Path.of(snapshotDir).toAbsolutePath().normalize();
        this.alertRetentionDays = alertRetentionDays;
        this.snapshotRetentionDays = snapshotRetentionDays;
        this.logRetentionDays = logRetentionDays;
        Files.createDirectories(this.snapshotDir);
    }

    @Scheduled(cron = "${chepai.retention.cron:0 30 3 * * *}")
    public void purge() {
        purgeAlerts();
        purgeSnapshotFiles();
        purgeLogs();
    }

    private void purgeAlerts() {
        if (alertRetentionDays <= 0) {
            return;
        }
        List<String> paths = alerts.listSnapshotPathsOlderThanDays(alertRetentionDays);
        int deleted = alerts.deleteOlderThanDays(alertRetentionDays);
        int filesRemoved = deleteSnapshotPaths(paths);
        log.info(
                "retention alerts: deletedRows={} snapshotFiles={} olderThanDays={}",
                deleted,
                filesRemoved,
                alertRetentionDays);
    }

    private void purgeSnapshotFiles() {
        if (snapshotRetentionDays <= 0) {
            return;
        }
        Instant cutoff = Instant.now().minus(snapshotRetentionDays, ChronoUnit.DAYS);
        int removed = 0;
        try (var stream = Files.list(snapshotDir)) {
            for (Path file : stream.toList()) {
                if (!Files.isRegularFile(file) || !file.getFileName().toString().endsWith(".jpg")) {
                    continue;
                }
                try {
                    if (Files.getLastModifiedTime(file).toInstant().isBefore(cutoff)) {
                        Files.deleteIfExists(file);
                        removed++;
                    }
                } catch (IOException ex) {
                    log.warn("retention failed to delete {}: {}", file, ex.getMessage());
                }
            }
        } catch (IOException ex) {
            log.warn("retention snapshot scan failed: {}", ex.getMessage());
            return;
        }
        if (removed > 0) {
            log.info("retention snapshots: deletedFiles={} olderThanDays={}", removed, snapshotRetentionDays);
        }
    }

    private void purgeLogs() {
        if (logRetentionDays <= 0) {
            return;
        }
        int deleted = edgeLogs.deleteOlderThanDays(logRetentionDays);
        if (deleted > 0) {
            log.info("retention edge logs: deletedRows={} olderThanDays={}", deleted, logRetentionDays);
        }
    }

    private int deleteSnapshotPaths(List<String> snapshotPaths) {
        Set<String> names = new HashSet<>();
        for (String path : snapshotPaths) {
            if (path == null || path.isBlank()) {
                continue;
            }
            Matcher m = SNAPSHOT_NAME.matcher(path);
            if (m.find()) {
                names.add(m.group(1));
            } else if (path.endsWith(".jpg")) {
                names.add(Path.of(path).getFileName().toString());
            }
        }
        int removed = 0;
        for (String name : names) {
            try {
                if (Files.deleteIfExists(snapshotDir.resolve(name))) {
                    removed++;
                }
            } catch (IOException ex) {
                log.warn("retention failed to delete snapshot {}: {}", name, ex.getMessage());
            }
        }
        return removed;
    }
}
