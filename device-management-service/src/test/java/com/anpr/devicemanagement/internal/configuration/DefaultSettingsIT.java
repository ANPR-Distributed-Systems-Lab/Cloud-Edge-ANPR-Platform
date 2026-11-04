package com.anpr.devicemanagement.internal.configuration;

import com.anpr.devicemanagement.api.configuration.ConfigurationApiMapper;
import com.anpr.devicemanagement.api.generated.model.DeviceConfigurationResponse;
import jakarta.validation.Validator;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

import java.time.Instant;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * The defaults in application.yaml satisfy the ranges of the contract: they are validated with the constraints the
 * generator derives from device-management-api.yaml, so a new device never starts with a configuration a person
 * could not save.
 */
@SpringBootTest
@ActiveProfiles("test")
class DefaultSettingsIT {

    @Autowired
    private DefaultSettings defaults;
    @Autowired
    private ConfigurationApiMapper mapper;
    @Autowired
    private Validator validator;

    @Test
    void theDefaultsSatisfyTheContract() {
        DeviceConfiguration configuration = DeviceConfiguration.initial(UUID.randomUUID(), defaults.newSettings(), Instant.EPOCH);
        configuration.setVersion(1L);

        DeviceConfigurationResponse response = mapper.toResponse(configuration);

        assertThat(validator.validate(response)).isEmpty();
    }

    @Test
    void everyCallGivesAnIndependentCopy() {
        DeviceSettings first = defaults.newSettings();
        DeviceSettings second = defaults.newSettings();

        first.getCamera().getExposure().setGain(20.0);

        assertThat(second.getCamera().getExposure().getGain()).isNotEqualTo(20.0);
        assertThat(defaults.newSettings().getCamera().getExposure().getGain()).isNotEqualTo(20.0);
    }
}
