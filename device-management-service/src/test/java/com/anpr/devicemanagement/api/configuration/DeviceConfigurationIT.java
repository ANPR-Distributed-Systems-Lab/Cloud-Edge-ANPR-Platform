package com.anpr.devicemanagement.api.configuration;

import com.anpr.devicemanagement.support.ApiTestSupport;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;

import java.util.UUID;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class DeviceConfigurationIT extends ApiTestSupport {

    @Test
    void aNewDeviceStartsWithTheDefaultsWhichItAndItsOwnerRead() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();

        mockMvc.perform(get("/api/v1/device/config").with(device(owner.deviceId())))
                .andExpect(status().isOk())
                .andExpect(header().exists("ETag"))
                .andExpect(jsonPath("$.deviceId").value(owner.deviceId().toString()))
                .andExpect(jsonPath("$.version").isNumber())
                .andExpect(jsonPath("$.updatedAt").exists())
                .andExpect(jsonPath("$.plateCooldownSeconds").value(60))
                .andExpect(jsonPath("$.batching.detectionsBatchSize").value(20))
                .andExpect(jsonPath("$.ml.ocrMinConfidence").value(0.6))
                .andExpect(jsonPath("$.intervals.metricsSeconds").value(60))
                .andExpect(jsonPath("$.camera.exposure.mode").value("MANUAL"))
                .andExpect(jsonPath("$.camera.whiteBalance.mode").value("DAYLIGHT"))
                .andExpect(jsonPath("$.camera.fps").value(3.0));
        mockMvc.perform(get("/api/v1/device/config").with(person(owner.accountId())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.deviceId").value(owner.deviceId().toString()));
    }

    @Test
    void pollingWithTheCurrentETagGives304() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();
        String etag = etagOf(owner);

        mockMvc.perform(get("/api/v1/device/config").with(device(owner.deviceId())).header("If-None-Match", etag))
                .andExpect(status().isNotModified())
                .andExpect(header().string("ETag", etag))
                .andExpect(content().string(""));
    }

    @Test
    void theOwnerReplacesTheConfigurationAndTheDeviceSeesTheNewVersion() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();
        String oldEtag = etagOf(owner);
        long version = versionOf(owner);

        mockMvc.perform(put("/api/v1/device/config").with(person(owner.accountId()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(updateRequest(version, 15)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.version").value(version + 1))
                .andExpect(jsonPath("$.intervals.metricsSeconds").value(15))
                .andExpect(header().string("ETag", "\"" + (version + 1) + "\""));

        mockMvc.perform(get("/api/v1/device/config").with(device(owner.deviceId())).header("If-None-Match", oldEtag))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.intervals.metricsSeconds").value(15))
                .andExpect(jsonPath("$.camera.exposure.mode").value("AUTO"));
    }

    @Test
    void savingOverAChangeNotSeenIsAConflict() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();
        long version = versionOf(owner);
        mockMvc.perform(put("/api/v1/device/config").with(person(owner.accountId()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(updateRequest(version, 15)))
                .andExpect(status().isOk());

        mockMvc.perform(put("/api/v1/device/config").with(person(owner.accountId()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(updateRequest(version, 20)))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("CONCURRENT_MODIFICATION"));
    }

    @Test
    void aValueOutsideTheContractRangeIsRefused() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();

        mockMvc.perform(put("/api/v1/device/config").with(person(owner.accountId()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(updateRequest(versionOf(owner), 2)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"))
                .andExpect(jsonPath("$.fields[0].field").value("intervals.metricsSeconds"))
                .andExpect(jsonPath("$.fields[0].code").value("RANGE"))
                .andExpect(jsonPath("$.fields[0].index").doesNotExist());
    }

    @Test
    void aDeviceMayNotEditItsConfiguration() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();

        mockMvc.perform(put("/api/v1/device/config").with(device(owner.deviceId()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(updateRequest(versionOf(owner), 15)))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value("FORBIDDEN"));
    }

    @Test
    void anotherPersonDoesNotSeeTheConfiguration() throws Exception {
        createPersonWithDevice();

        mockMvc.perform(get("/api/v1/device/config").with(person(UUID.randomUUID())))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("DEVICE_NOT_FOUND"));
    }

    private String etagOf(PersonWithDevice owner) throws Exception {
        return mockMvc.perform(get("/api/v1/device/config").with(device(owner.deviceId())))
                .andReturn().getResponse().getHeader("ETag");
    }

    private long versionOf(PersonWithDevice owner) throws Exception {
        return Long.parseLong(etagOf(owner).replace("\"", ""));
    }

    private static String updateRequest(long version, int metricsSeconds) {
        return """
                {
                  "version": %d,
                  "plateCooldownSeconds": 30,
                  "batching": { "detectionsBatchSize": 10, "locationsBatchSize": 50, "imageUrlsBatchSize": 10, "maxBatchDelaySeconds": 5 },
                  "ml": { "detectorMinConfidence": 0.4, "ocrMinConfidence": 0.7, "minPlateWidthPx": 80 },
                  "intervals": { "metricsSeconds": %d, "configPollSeconds": 30, "alertsPollSeconds": 30, "locationSampleSeconds": 2 },
                  "camera": {
                    "exposure": { "mode": "AUTO", "exposureUs": 1000, "gain": 2.0, "maxExposureUs": 3000, "maxGain": 8.0, "targetBrightness": 0.45 },
                    "whiteBalance": { "mode": "MANUAL", "redGain": 1.8, "blueGain": 1.5 },
                    "fps": 4.0
                  }
                }
                """.formatted(version, metricsSeconds);
    }
}
