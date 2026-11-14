package com.anpr.devicemanagement.api.models;

import com.anpr.devicemanagement.internal.models.ModelName;
import com.anpr.devicemanagement.support.ApiTestSupport;
import org.junit.jupiter.api.Test;

import java.util.Optional;
import java.util.UUID;

import static org.hamcrest.Matchers.hasSize;
import static org.hamcrest.Matchers.startsWith;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class DeviceModelsIT extends ApiTestSupport {

    @Test
    void theDeviceGetsSignedUrlsForTheVersionsOfItsConfiguration() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();

        mockMvc.perform(get("/api/v1/device/models").with(device(owner.deviceId())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.deviceId").value(owner.deviceId().toString()))
                .andExpect(jsonPath("$.detector.version").value("v2"))
                .andExpect(jsonPath("$.ocr.version").value("v3"))
                .andExpect(jsonPath("$.ocr.files", hasSize(1)))
                .andExpect(jsonPath("$.ocr.files[0].name").value("model.onnx"))
                .andExpect(jsonPath("$.ocr.files[0].sha256").value("a".repeat(64)))
                .andExpect(jsonPath("$.ocr.files[0].sizeBytes").value(1234))
                .andExpect(jsonPath("$.ocr.files[0].url").value(startsWith(
                        "https://test-models-bucket.s3.eu-central-1.amazonaws.com/models/ocr/v3/model.onnx?")))
                .andExpect(jsonPath("$.ocr.files[0].expiresAt").exists());
    }

    @Test
    void aVersionThatIsNotPublishedIsAConflict() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();
        when(releases.find(ModelName.DETECTOR, "v2")).thenReturn(Optional.empty());

        mockMvc.perform(get("/api/v1/device/models").with(device(owner.deviceId())))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("MODEL_NOT_PUBLISHED"));
    }

    @Test
    void aPersonGetsNoDownloadUrls() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();

        mockMvc.perform(get("/api/v1/device/models").with(person(owner.accountId())))
                .andExpect(status().isForbidden());
    }

    @Test
    void anUnregisteredDeviceGetsNoDownloadUrls() throws Exception {
        mockMvc.perform(get("/api/v1/device/models").with(device(UUID.randomUUID())))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("DEVICE_NOT_FOUND"));
    }
}
