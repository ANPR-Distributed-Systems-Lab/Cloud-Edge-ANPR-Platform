package com.anpr.devicemanagement.internal.configuration;

import lombok.RequiredArgsConstructor;
import org.mapstruct.Mapper;
import org.mapstruct.control.DeepClone;
import org.springframework.stereotype.Component;

/** Hands out the default settings of the service. */
@Component
@RequiredArgsConstructor
public class DefaultSettings {
    private final DefaultSettingsProperties properties;
    private final Copier copier;

    /** A deep copy: the settings are mutable, so a new configuration must not share any object with the defaults. */
    public DeviceSettings newSettings() {
        return copier.copy(properties.defaults());
    }

    @Mapper(componentModel = "spring", mappingControl = DeepClone.class)
    interface Copier {
        DeviceSettings copy(DeviceSettings settings);
    }
}
