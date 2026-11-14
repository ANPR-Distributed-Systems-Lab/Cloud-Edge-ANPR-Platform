package com.anpr.devicemanagement.internal.models;

import com.anpr.devicemanagement.internal.configuration.DeviceSettings;
import com.anpr.devicemanagement.shared.error.ConflictException;
import com.anpr.devicemanagement.shared.error.ErrorCodes;
import com.anpr.devicemanagement.shared.error.FieldViolation;
import com.anpr.devicemanagement.shared.error.ValidationException;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.Arrays;
import java.util.List;

/** Which model versions exist: a configuration may only name published ones. */
@Component
@RequiredArgsConstructor
public class PublishedModels {
    private final ModelReleases releases;

    /** @throws ValidationException MODEL_NOT_PUBLISHED for every version of the configuration that is not published */
    public void requirePublished(DeviceSettings.Models models) {
        List<FieldViolation> violations = Arrays.stream(ModelName.values())
                .filter(model -> releases.find(model, model.versionIn(models)).isEmpty())
                .map(model -> new FieldViolation(null, "models." + model.id(), ErrorCodes.MODEL_NOT_PUBLISHED,
                        "Version " + model.versionIn(models) + " of the " + model.id() + " is not published"))
                .toList();
        if (!violations.isEmpty()) {
            throw new ValidationException(violations);
        }
    }

    /** @throws ConflictException MODEL_NOT_PUBLISHED when a configuration names a version that is not published */
    public ModelRelease release(ModelName model, String version) {
        return releases.find(model, version).orElseThrow(() -> new ConflictException(ErrorCodes.MODEL_NOT_PUBLISHED,
                "Version " + version + " of the " + model.id() + " is not published"));
    }
}
