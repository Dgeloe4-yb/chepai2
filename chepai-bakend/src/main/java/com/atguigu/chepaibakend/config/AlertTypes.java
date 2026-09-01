package com.atguigu.chepaibakend.config;

import java.util.List;
import java.util.Set;

public final class AlertTypes {
    private AlertTypes() {}

    public static final Set<String> INGEST = Set.of(
            "oil_car",
            "bad_park",
            "mini_ad",
            "dual_slot",
            "car_in_bus_slot",
            "bus_in_restricted",
            "non_sedan",
            "gun_misplace");

    public static final List<String> VOICE = List.of(
            "oil_car",
            "bad_park",
            "mini_ad",
            "dual_slot",
            "car_in_bus_slot",
            "bus_in_restricted");

    public static boolean isIngest(String t) {
        return t != null && INGEST.contains(t);
    }

    public static boolean isVoice(String t) {
        return t != null && VOICE.contains(t);
    }
}
