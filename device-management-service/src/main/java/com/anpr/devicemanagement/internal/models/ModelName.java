package com.anpr.devicemanagement.internal.models;

import com.anpr.devicemanagement.internal.configuration.DeviceSettings;

import java.util.function.Function;

/** The models a device runs: the plate detector, then the OCR of each plate it finds. */
public enum ModelName {
    DETECTOR("detector", DeviceSettings.Models::getDetector),
    OCR("ocr", DeviceSettings.Models::getOcr);

    private final String id;
    private final Function<DeviceSettings.Models, String> version;

    ModelName(String id, Function<DeviceSettings.Models, String> version) {
        this.id = id;
        this.version = version;
    }

    /** The name in S3 keys, release descriptions and field paths ({@code models.detector}). */
    public String id() {
        return id;
    }

    /** The version of this model named in a configuration. */
    public String versionIn(DeviceSettings.Models models) {
        return version.apply(models);
    }
}
