package com.anpr.operations.api.search;

import com.anpr.operations.TestcontainersConfiguration;
import com.anpr.operations.internal.detections.DetectionService;
import com.anpr.operations.internal.detections.DetectionService.NewDetection;
import com.anpr.operations.internal.devices.DevicePairingService;
import com.anpr.operations.shared.storage.ImageUrlSigner;
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

import static org.hamcrest.Matchers.contains;
import static org.hamcrest.Matchers.nullValue;
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
class DetectionSearchIT {
    private static final String ACCOUNT_HEADER = "X-Account-Id";
    private static final OffsetDateTime T0 = OffsetDateTime.of(2026, 10, 30, 9, 0, 0, 0, ZoneOffset.UTC);

    @Autowired private MockMvc mockMvc;
    @Autowired private DevicePairingService pairingService;
    @Autowired private DetectionService detectionService;
    // Real signatures change every second; the contract test needs a stable URL. ImageUrlSignerTest covers signing.
    @MockitoBean private ImageUrlSigner imageUrlSigner;

    @Test
    void returnsOnlyDetectionsOfTheCallerAccount() throws Exception {
        UUID account = UUID.randomUUID();
        store(account, detection("WA10001", T0));
        store(UUID.randomUUID(), detection("WA10001", T0));

        mockMvc.perform(get("/api/v1/detections/search").header(ACCOUNT_HEADER, account.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.page.totalElements").value(1));
    }

    @Test
    void filtersByTheExactPlate() throws Exception {
        UUID account = UUID.randomUUID();
        store(account, detection("WA12345", T0), detection("WA123456", T0), detection("KR12345", T0));

        mockMvc.perform(get("/api/v1/detections/search").param("plate", "WA12345")
                        .header(ACCOUNT_HEADER, account.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items[*].plate", contains("WA12345")));
    }

    @Test
    void fromIsInclusiveAndToIsExclusive() throws Exception {
        UUID account = UUID.randomUUID();
        store(account, detection("WA20001", T0), detection("WA20002", T0.plusHours(1)));

        mockMvc.perform(get("/api/v1/detections/search")
                        .param("from", T0.toString()).param("to", T0.plusHours(1).toString())
                        .header(ACCOUNT_HEADER, account.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items[*].plate", contains("WA20001")));
    }

    @Test
    void toBeforeFromReturns400() throws Exception {
        mockMvc.perform(get("/api/v1/detections/search")
                        .param("from", T0.toString()).param("to", T0.minusHours(1).toString())
                        .header(ACCOUNT_HEADER, UUID.randomUUID().toString()))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_TIME_RANGE"));
    }

    @Test
    void pageSizeAboveTheLimitReturns400() throws Exception {
        mockMvc.perform(get("/api/v1/detections/search").param("size", "1001")
                        .header(ACCOUNT_HEADER, UUID.randomUUID().toString()))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"));
    }

    @Test
    void newestDetectionsComeFirstByDefaultAndPlateSortingIsAvailable() throws Exception {
        UUID account = UUID.randomUUID();
        store(account, detection("KR30001", T0), detection("WA30002", T0.plusHours(2)), detection("GD30003", T0.plusHours(1)));

        mockMvc.perform(get("/api/v1/detections/search").header(ACCOUNT_HEADER, account.toString()))
                .andExpect(jsonPath("$.items[*].plate", contains("WA30002", "GD30003", "KR30001")));

        mockMvc.perform(get("/api/v1/detections/search").param("sort", "PLATE").param("direction", "ASC")
                        .header(ACCOUNT_HEADER, account.toString()))
                .andExpect(jsonPath("$.items[*].plate", contains("GD30003", "KR30001", "WA30002")));
    }

    @Test
    void detectionOfAPlateWithAnAlertCarriesItsId() throws Exception {
        UUID account = UUID.randomUUID();
        store(account, detection("WA40001", T0), detection("WA40002", T0.plusMinutes(1)));
        String alertId = createAlert(account, "WA40001");

        mockMvc.perform(get("/api/v1/detections/search").param("sort", "PLATE").param("direction", "ASC")
                        .header(ACCOUNT_HEADER, account.toString()))
                .andExpect(jsonPath("$.items[0].alertId").value(alertId))
                .andExpect(jsonPath("$.items[1].alertId").value(nullValue()));
    }

    @Test
    void responseHasTheShapeOfTheContract() throws Exception {
        when(imageUrlSigner.urlOf(anyString())).thenAnswer(call -> URI.create("https://images.test/" + call.getArgument(0)));
        UUID account = UUID.fromString("5e1c0000-0000-4000-8000-000000000001");
        UUID device = UUID.fromString("5e1c0000-0000-4000-8000-000000000002");
        pairingService.pair(device, account, 1);
        detectionService.store(device, List.of(new NewDetection(
                UUID.fromString("5e1c0000-0000-4000-8000-000000000003"), "WA12345",
                OffsetDateTime.parse("2026-10-30T09:14:22.381Z"), 52.229676, 21.012229, 0.94, 0.88,
                "images/5e1c0000-0000-4000-8000-000000000002/2026/10/30/frame.jpg")));

        mockMvc.perform(get("/api/v1/detections/search").header(ACCOUNT_HEADER, account.toString()))
                .andExpect(status().isOk())
                .andExpect(content().json(resource("detections/search-response.json"), JsonCompareMode.STRICT));
    }

    @Test
    void plateSuggestionsAreDistinctPlatesOfTheAccountNewestFirst() throws Exception {
        UUID account = UUID.randomUUID();
        store(account, detection("WA50001", T0), detection("WA50001", T0.plusHours(3)),
                detection("WA50002", T0.plusHours(1)), detection("KR50003", T0.plusHours(2)));
        store(UUID.randomUUID(), detection("WA50009", T0.plusHours(5)));

        mockMvc.perform(get("/api/v1/detections/plate-suggestions").param("q", "WA5")
                        .header(ACCOUNT_HEADER, account.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items[*].plate", contains("WA50001", "WA50002")))
                .andExpect(jsonPath("$.items[0].lastDetectedAt").value("2026-10-30T12:00:00Z"));

        mockMvc.perform(get("/api/v1/detections/plate-suggestions").param("q", "WA5").param("limit", "1")
                        .header(ACCOUNT_HEADER, account.toString()))
                .andExpect(jsonPath("$.items[*].plate", contains("WA50001")));
    }

    private void store(UUID account, NewDetection... detections) {
        UUID device = UUID.randomUUID();
        pairingService.pair(device, account, 1);
        detectionService.store(device, List.of(detections));
    }

    private static NewDetection detection(String plate, OffsetDateTime detectedAt) {
        return new NewDetection(UUID.randomUUID(), plate, detectedAt, 52.2, 21.0, 0.9, 0.8, "images/x.jpg");
    }

    private String createAlert(UUID account, String plate) throws Exception {
        String body = mockMvc.perform(post("/api/v1/alerts")
                        .header(ACCOUNT_HEADER, account.toString())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{ \"plate\": \"" + plate + "\" }"))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
        return com.jayway.jsonpath.JsonPath.read(body, "$.alertId");
    }

    private static String resource(String path) throws Exception {
        return new ClassPathResource(path).getContentAsString(StandardCharsets.UTF_8);
    }
}