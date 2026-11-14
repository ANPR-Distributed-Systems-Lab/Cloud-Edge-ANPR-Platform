package com.anpr.devicemanagement.local;

import com.anpr.devicemanagement.internal.models.ModelName;
import com.anpr.devicemanagement.internal.models.ModelRelease;
import com.anpr.devicemanagement.internal.models.ModelReleases;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.Optional;

/**
 * Stand-in for the models bucket on a developer machine: every version counts as published, with the files the
 * device needs. There is no local S3, so the checksums are zeros and the download URLs lead nowhere (as the
 * upload URLs of photos). rpi-edge/tools/dev_cloud.py serves real models to a device without AWS.
 */
@Component
@Profile("local")
public class LocalModelReleases implements ModelReleases {
    private static final String NO_CHECKSUM = "0".repeat(64);

    @Override
    public Optional<ModelRelease> find(ModelName model, String version) {
        List<String> files = switch (model) {
            case DETECTOR -> List.of("model.onnx");
            case OCR -> List.of("model.onnx", "plate_config.yaml");
        };
        return Optional.of(new ModelRelease(model.id(), version,
                files.stream().map(name -> new ModelRelease.File(name, NO_CHECKSUM, 0)).toList()));
    }
}
