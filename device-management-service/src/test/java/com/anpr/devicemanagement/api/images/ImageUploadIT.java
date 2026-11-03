package com.anpr.devicemanagement.api.images;

import com.anpr.devicemanagement.support.ApiTestSupport;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;

import java.time.Instant;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.UUID;

import static org.hamcrest.Matchers.hasSize;
import static org.hamcrest.Matchers.startsWith;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class ImageUploadIT extends ApiTestSupport {

    @Test
    void theDeviceGetsAKeyUnderItsPrefixAndASignedUrl() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();
        UUID frameId = UUID.randomUUID();
        Instant capturedAt = Instant.now().minusSeconds(30);
        String date = DateTimeFormatter.ofPattern("yyyy/MM/dd").withZone(ZoneOffset.UTC).format(capturedAt);
        String key = "images/" + owner.deviceId() + "/" + date + "/" + frameId + ".jpg";

        mockMvc.perform(post("/api/v1/images/presigned-urls").with(device(owner.deviceId()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(request(frameId, capturedAt)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.uploads", hasSize(1)))
                .andExpect(jsonPath("$.uploads[0].frameId").value(frameId.toString()))
                .andExpect(jsonPath("$.uploads[0].imageKey").value(key))
                .andExpect(jsonPath("$.uploads[0].uploadUrl").value(startsWith(
                        "https://test-images-bucket.s3.eu-central-1.amazonaws.com/" + key + "?")))
                .andExpect(jsonPath("$.uploads[0].expiresAt").exists());
    }

    @Test
    void aPersonGetsNoUploadUrls() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();

        mockMvc.perform(post("/api/v1/images/presigned-urls").with(person(owner.accountId()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(request(UUID.randomUUID(), Instant.now())))
                .andExpect(status().isForbidden());
    }

    @Test
    void anUnregisteredDeviceGetsNoUploadUrls() throws Exception {
        mockMvc.perform(post("/api/v1/images/presigned-urls").with(device(UUID.randomUUID()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(request(UUID.randomUUID(), Instant.now())))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("DEVICE_NOT_FOUND"));
    }

    private static String request(UUID frameId, Instant capturedAt) {
        return """
                { "frames": [ { "frameId": "%s", "capturedAt": "%s" } ] }
                """.formatted(frameId, capturedAt);
    }
}
