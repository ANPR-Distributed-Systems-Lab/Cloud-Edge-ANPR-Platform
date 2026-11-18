package com.anpr.operations.api.detections;

import com.anpr.operations.TestcontainersConfiguration;
import com.anpr.operations.internal.detections.DetectionService;
import com.anpr.operations.internal.detections.DetectionService.NewDetection;
import com.anpr.operations.internal.devices.DevicePairingService;
import com.anpr.operations.shared.storage.ImageUrlSigner;
import com.jayway.jsonpath.JsonPath;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.core.io.ClassPathResource;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.json.JsonCompareMode;
import org.springframework.test.web.servlet.MockMvc;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;

import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@Import(TestcontainersConfiguration.class)
class DetectionsControllerIT {
    private static final String ACCOUNT_HEADER = "X-Account-Id";
    private static final OffsetDateTime T0 = OffsetDateTime.of(2026, 10, 30, 9, 0, 0, 0, ZoneOffset.UTC);

    @Autowired private MockMvc mockMvc;
    @Autowired private DevicePairingService pairingService;
    @Autowired private DetectionService detectionService;
    // Real signatures change every second; the contract test needs a stable URL. ImageUrlSignerTest covers signing.
    @MockitoBean private ImageUrlSigner imageUrlSigner;

    @Test
    void responseHasTheShapeOfTheContract() throws Exception {
        when(imageUrlSigner.urlOf(anyString())).thenAnswer(call -> URI.create("https://images.test/" + call.getArgument(0)));
        UUID account = UUID.fromString("5e1c0000-0000-4000-8000-000000000011");
        UUID device = UUID.fromString("5e1c0000-0000-4000-8000-000000000012");
        UUID detectionId = UUID.fromString("5e1c0000-0000-4000-8000-000000000013");
        pairingService.pair(device, account, 1);
        detectionService.store(device, List.of(new NewDetection(detectionId, "WA12345",
                OffsetDateTime.parse("2026-10-30T09:14:22.381Z"), 52.229676, 21.012229, 0.94, 0.88,
                "images/5e1c0000-0000-4000-8000-000000000012/2026/10/30/frame.jpg")));

        mockMvc.perform(get("/api/v1/detections/{id}", detectionId).header(ACCOUNT_HEADER, account.toString()))
                .andExpect(status().isOk())
                .andExpect(content().json(resource("detections/detection-response.json"), JsonCompareMode.STRICT));
    }

    @Test
    void detectionOfAPlateWithAnAlertCarriesItsId() throws Exception {
        UUID account = UUID.randomUUID();
        UUID detectionId = store(account, "WA70001");
        String alertId = createAlert(account, "WA70001");

        mockMvc.perform(get("/api/v1/detections/{id}", detectionId).header(ACCOUNT_HEADER, account.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.alertId").value(alertId));
    }

    @Test
    void detectionOfAnotherAccountIsNotFound() throws Exception {
        UUID detectionId = store(UUID.randomUUID(), "WA70002");

        mockMvc.perform(get("/api/v1/detections/{id}", detectionId).header(ACCOUNT_HEADER, UUID.randomUUID().toString()))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("DETECTION_NOT_FOUND"))
                .andExpect(jsonPath("$.requestId").exists());
    }

    @Test
    void unknownDetectionIsNotFound() throws Exception {
        mockMvc.perform(get("/api/v1/detections/{id}", UUID.randomUUID())
                        .header(ACCOUNT_HEADER, UUID.randomUUID().toString()))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("DETECTION_NOT_FOUND"));
    }

    private UUID store(UUID account, String plate) {
        UUID device = UUID.randomUUID();
        UUID detectionId = UUID.randomUUID();
        pairingService.pair(device, account, 1);
        detectionService.store(device, List.of(
                new NewDetection(detectionId, plate, T0, 52.2, 21.0, 0.9, 0.8, "images/x.jpg")));
        return detectionId;
    }

    private String createAlert(UUID account, String plate) throws Exception {
        String body = mockMvc.perform(post("/api/v1/alerts")
                        .header(ACCOUNT_HEADER, account.toString())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{ \"plate\": \"" + plate + "\" }"))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
        return JsonPath.read(body, "$.alertId");
    }

    private static String resource(String path) throws Exception {
        return new ClassPathResource(path).getContentAsString(StandardCharsets.UTF_8);
    }
}
