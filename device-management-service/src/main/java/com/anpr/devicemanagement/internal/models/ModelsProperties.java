package com.anpr.devicemanagement.internal.models;

import jakarta.validation.constraints.NotNull;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

import java.time.Duration;

/**
 * @param downloadUrlValidity how long a presigned download URL of a model file may be used
 */
@Validated
@ConfigurationProperties(prefix = "app.models")
public record ModelsProperties(@NotNull Duration downloadUrlValidity) {
}
