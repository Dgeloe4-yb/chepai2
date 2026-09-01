package com.atguigu.chepaibakend.config;

import java.util.ArrayList;
import java.util.List;
import java.util.Set;

/** Detection capabilities a USER may be granted; union is pushed to assigned edge boxes. */
public final class FeatureCatalog {
    private FeatureCatalog() {}

    public static final List<String> ALL = List.of(
            "oil_car",
            "bad_park",
            "mini_ad",
            "dual_slot",
            "car_in_bus_slot",
            "bus_in_restricted");

    public static final Set<String> ALL_SET = Set.copyOf(ALL);

    public static boolean isKnown(String key) {
        return key != null && ALL_SET.contains(key);
    }

    /** Alert list filter: include legacy ingest alias for bus_in_restricted. */
    public static List<String> expandForAlertQuery(List<String> features) {
        if (features == null) {
            return null;
        }
        List<String> out = new ArrayList<>(features);
        if (out.contains("bus_in_restricted") && !out.contains("non_sedan")) {
            out.add("non_sedan");
        }
        return out;
    }
}
