package com.anpr.devicemanagement.internal.configuration;

import com.anpr.devicemanagement.internal.devices.DeviceLookup;
import com.anpr.devicemanagement.internal.models.PublishedModels;
import com.anpr.devicemanagement.shared.error.ConflictException;
import com.anpr.devicemanagement.shared.error.ErrorCodes;
import com.anpr.devicemanagement.shared.error.TechnicalException;
import com.anpr.devicemanagement.shared.security.Caller;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

import java.time.Clock;
import java.util.Objects;
import java.util.UUID;

/** View 4: the device reads its configuration, the owner reads and replaces it. */
@Service
@RequiredArgsConstructor
public class ConfigurationService {
    private final DeviceLookup deviceLookup;
    private final DeviceConfigurationRepository configurations;
    private final PublishedModels publishedModels;
    private final Clock clock;

    public DeviceConfiguration get(Caller caller) {
        return get(deviceLookup.deviceOf(caller).getDeviceId());
    }

    /** The configuration of a registered device; it is created together with the device, so it always exists. */
    public DeviceConfiguration get(UUID deviceId) {
        return configurations.findByDeviceId(deviceId)
                .orElseThrow(() -> new TechnicalException("Configuration of device " + deviceId + " is missing"));
    }

    /**
     * Replaces the settings of the owner's device.
     *
     * @param expectedVersion the version the person read; a different stored version means they would overwrite a
     *                        change they have not seen
     * @throws com.anpr.devicemanagement.shared.error.ValidationException MODEL_NOT_PUBLISHED for a model version the
     *                        device could not download
     */
    public DeviceConfiguration update(Caller caller, long expectedVersion, DeviceSettings settings) {
        caller.asUser();
        DeviceConfiguration configuration = get(caller);
        if (!Objects.equals(configuration.getVersion(), expectedVersion)) {
            throw new ConflictException(ErrorCodes.CONCURRENT_MODIFICATION, "Configuration was modified by someone else");
        }
        publishedModels.requirePublished(settings.getModels());
        configuration.replaceSettings(settings, clock.instant());
        return configurations.update(configuration);
    }
}
