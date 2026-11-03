package com.anpr.devicemanagement.internal.configuration;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

/**
 * The settings a new device starts with ({@code app.configuration.defaults} in application.yaml). Every value is
 * required; DefaultSettingsIT checks that they also satisfy the ranges of the contract.
 */
@Validated
@ConfigurationProperties(prefix = "app.configuration")
public record DefaultSettingsProperties(@Valid @NotNull DeviceSettings defaults) {
}
