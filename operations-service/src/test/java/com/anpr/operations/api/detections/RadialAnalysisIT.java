package com.anpr.operations.api.detections;

import com.anpr.operations.TestcontainersConfiguration;
import com.anpr.operations.internal.detections.DetectionService;
import com.anpr.operations.internal.detections.DetectionService.NewDetection;
import com.anpr.operations.internal.devices.DevicePairingService;
import com.anpr.operations.internal.locations.DeviceLocationService;
import com.anpr.operations.internal.locations.DeviceLocationService.NewDeviceLocation;
import com.anpr.operations.shared.storage.ImageUrlSigner;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.core.io.ClassPathResource;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.json.JsonCompareMode;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.stream.IntStream;

import static org.hamcrest.Matchers.contains;
import static org.hamcrest.Matchers.containsInAnyOrder;
import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.empty;
import static org.hamcrest.Matchers.not;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@Import(TestcontainersConfiguration.class)
class RadialAnalysisIT {
    private static final String ACCOUNT_HEADER = "X-Account-Id";
    private static final String RADIAL_ANALYSIS = "/api/v1/detections/radial-analysis";
    private static final OffsetDateTime FROM = OffsetDateTime.of(2026, 10, 30, 9, 0, 0, 0, ZoneOffset.UTC);
    private static final OffsetDateTime TO = FROM.plusHours(1);
    private static final double LAT = 52.2297;
    private static final double LON = 21.0122;
    /** About 100 m north of the centre (one degree of latitude is about 111 km). */
    private static final double LAT_100_M_NORTH = LAT + 0.0009;
    /** About 1 km north of the centre. */
    private static final double LAT_1_KM_NORTH = LAT + 0.009;
    private static final int LIMIT = 5000;

    @Autowired private MockMvc mockMvc;
    @Autowired private DevicePairingService pairingService;
    @Autowired private DetectionService detectionService;
    @Autowired private DeviceLocationService locationService;
    // Real signatures change every second; the contract test needs a stable URL. ImageUrlSignerTest covers signing.
    @MockitoBean private ImageUrlSigner imageUrlSigner;

    @Test
    void returnsOnlyDetectionsInsideTheRadius() throws Exception {
        UUID account = UUID.randomUUID();
        UUID device = pairedDevice(account);
        detectionService.store(device, List.of(
                detection("WA80001", FROM.plusMinutes(1), LAT_100_M_NORTH),
                detection("WA80002", FROM.plusMinutes(2), LAT_1_KM_NORTH)));

        mockMvc.perform(radialAnalysis(account, "radiusMeters", "500"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.detections[*].plate", contains("WA80001")));
    }

    @Test
    void returnsOnlyDataOfTheCallerAccount() throws Exception {
        UUID account = UUID.randomUUID();
        UUID device = pairedDevice(account);
        UUID otherDevice = pairedDevice(UUID.randomUUID());
        detectionService.store(device, List.of(detection("WA80011", FROM.plusMinutes(1), LAT)));
        detectionService.store(otherDevice, List.of(detection("WA80012", FROM.plusMinutes(1), LAT)));
        locate(device, FROM.plusMinutes(1));
        locate(otherDevice, FROM.plusMinutes(1));

        mockMvc.perform(radialAnalysis(account))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.detections[*].plate", contains("WA80011")))
                .andExpect(jsonPath("$.tracks[*].deviceId", contains(device.toString())));
    }

    @Test
    void fromIsInclusiveAndToIsExclusive() throws Exception {
        UUID account = UUID.randomUUID();
        UUID device = pairedDevice(account);
        detectionService.store(device, List.of(
                detection("WA80021", FROM.minusSeconds(1), LAT),
                detection("WA80022", FROM, LAT),
                detection("WA80023", TO, LAT)));
        locate(device, FROM.minusSeconds(1), FROM, TO);

        mockMvc.perform(radialAnalysis(account))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.detections[*].plate", contains("WA80022")))
                .andExpect(jsonPath("$.tracks[0].points[*].recordedAt", contains("2026-10-30T09:00:00Z")));
    }

    @Test
    void detectionsComeOldestFirst() throws Exception {
        UUID account = UUID.randomUUID();
        UUID device = pairedDevice(account);
        detectionService.store(device, List.of(
                detection("WA80032", FROM.plusMinutes(2), LAT),
                detection("WA80031", FROM.plusMinutes(1), LAT),
                detection("WA80033", FROM.plusMinutes(3), LAT)));

        mockMvc.perform(radialAnalysis(account))
                .andExpect(jsonPath("$.detections[*].plate", contains("WA80031", "WA80032", "WA80033")));
    }

    @Test
    void theRouteIsNotClippedToTheRadius() throws Exception {
        UUID account = UUID.randomUUID();
        UUID device = pairedDevice(account);
        locationService.store(device, List.of(
                new NewDeviceLocation(UUID.randomUUID(), FROM.plusMinutes(1), LAT, LON),
                new NewDeviceLocation(UUID.randomUUID(), FROM.plusMinutes(2), LAT_1_KM_NORTH, LON)));

        mockMvc.perform(radialAnalysis(account, "radiusMeters", "500"))
                .andExpect(jsonPath("$.tracks[0].points[*].position.lat", contains(LAT, LAT_1_KM_NORTH)));
    }

    @Test
    void withTheDefaultIntervalTheRouteHasEveryPoint() throws Exception {
        UUID account = UUID.randomUUID();
        UUID device = pairedDevice(account);
        locate(device, FROM.plusSeconds(1), FROM.plusSeconds(2), FROM.plusSeconds(3));

        mockMvc.perform(radialAnalysis(account))
                .andExpect(jsonPath("$.tracks[0].points[*].recordedAt",
                        contains("2026-10-30T09:00:01Z", "2026-10-30T09:00:02Z", "2026-10-30T09:00:03Z")))
                .andExpect(jsonPath("$.tracks[0].truncated").value(false));
    }

    @Test
    void theRouteKeepsTheFirstPointOfEachWindowCountedFromFrom() throws Exception {
        UUID account = UUID.randomUUID();
        UUID device = pairedDevice(account);
        // One fix per second from 09:00:05 to 09:00:24. Windows of 10 s from 'from' (09:00:05) keep 05 and 15;
        // windows aligned to full 10 seconds would keep 05, 10 and 20 instead.
        OffsetDateTime from = FROM.plusSeconds(5);
        locate(device, IntStream.range(0, 20).mapToObj(from::plusSeconds).toArray(OffsetDateTime[]::new));

        mockMvc.perform(radialAnalysis(account, "from", from.toString(), "trackIntervalSeconds", "10"))
                .andExpect(jsonPath("$.tracks[0].points[*].recordedAt",
                        contains("2026-10-30T09:00:05Z", "2026-10-30T09:00:15Z")));
    }

    @Test
    void aReplacedDeviceKeepsItsOwnRoute() throws Exception {
        UUID account = UUID.randomUUID();
        UUID replaced = pairedDevice(account);
        locate(replaced, FROM.plusMinutes(1));
        UUID current = replace(replaced, account);
        locate(current, FROM.plusMinutes(2));

        mockMvc.perform(radialAnalysis(account))
                .andExpect(jsonPath("$.tracks.length()").value(2))
                .andExpect(jsonPath("$.tracks[*].points[0].recordedAt",
                        containsInAnyOrder("2026-10-30T09:01:00Z", "2026-10-30T09:02:00Z")));
    }

    @Test
    void anAccountWithNoDataGetsEmptyLists() throws Exception {
        mockMvc.perform(radialAnalysis(UUID.randomUUID()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.detections", empty()))
                .andExpect(jsonPath("$.tracks", empty()))
                .andExpect(jsonPath("$.truncated").value(false));
    }

    /** The limits are counted by the database: detections overall, route points per device. */
    @Test
    void aboveTheLimitsTheMostRecentAreKeptAndMarkedTruncated() throws Exception {
        UUID account = UUID.randomUUID();
        UUID otherDevice = pairedDevice(account);
        locate(otherDevice, FROM.plusMinutes(1));
        UUID device = replace(otherDevice, account);
        // Two above the limit: the service asks for one more than the limit, so with only one extra the database
        // would return every row and the choice of the most recent ones would not be tested.
        int stored = LIMIT + 2;
        detectionService.store(device, IntStream.range(0, stored)
                .mapToObj(i -> detection("WA80041", FROM.plusSeconds(i), LAT)).toList());
        locate(device, IntStream.range(0, stored).mapToObj(FROM::plusSeconds).toArray(OffsetDateTime[]::new));

        // 5002 seconds are longer than the default hour.
        mockMvc.perform(radialAnalysis(account, "to", FROM.plusHours(2).toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.truncated").value(true))
                .andExpect(jsonPath("$.detections.length()").value(LIMIT))
                .andExpect(jsonPath("$.detections[0].detectedAt").value("2026-10-30T09:00:02Z"))
                .andExpect(jsonPath("$.tracks[?(@.deviceId == '%s')].truncated".formatted(device)).value(true))
                .andExpect(jsonPath("$.tracks[?(@.deviceId == '%s')].points.length()".formatted(device)).value(LIMIT))
                .andExpect(jsonPath("$.tracks[?(@.deviceId == '%s')].points[0].recordedAt".formatted(device))
                        .value("2026-10-30T09:00:02Z"))
                .andExpect(jsonPath("$.tracks[?(@.deviceId == '%s')].truncated".formatted(otherDevice)).value(false));
    }

    @Test
    void exactlySevenDaysIsAccepted() throws Exception {
        mockMvc.perform(radialAnalysis(UUID.randomUUID(), "to", FROM.plusDays(7).toString()))
                .andExpect(status().isOk());
    }

    @Test
    void aRangeLongerThanSevenDaysReturns400() throws Exception {
        mockMvc.perform(radialAnalysis(UUID.randomUUID(), "to", FROM.plusDays(7).plusSeconds(1).toString()))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"))
                .andExpect(jsonPath("$.requestId").exists())
                .andExpect(content().string(not(containsString("com.anpr"))));
    }

    @Test
    void toNotAfterFromReturns400() throws Exception {
        mockMvc.perform(radialAnalysis(UUID.randomUUID(), "to", FROM.toString()))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_TIME_RANGE"));
    }

    @ParameterizedTest
    @CsvSource({
            "radiusMeters, 24",
            "radiusMeters, 5001",
            "lat, 90.1",
            "lon, -180.1",
            "trackIntervalSeconds, 0",
            "trackIntervalSeconds, 181",
            "from, yesterday"})
    void aParameterOutsideTheContractReturns400(String name, String value) throws Exception {
        mockMvc.perform(radialAnalysis(UUID.randomUUID(), name, value))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"));
    }

    @Test
    void aMissingRequiredParameterReturns400() throws Exception {
        mockMvc.perform(get(RADIAL_ANALYSIS).param("lat", String.valueOf(LAT)).param("lon", String.valueOf(LON))
                        .param("from", FROM.toString()).param("to", TO.toString())
                        .header(ACCOUNT_HEADER, UUID.randomUUID().toString()))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"));
    }

    @Test
    void responseHasTheShapeOfTheContract() throws Exception {
        when(imageUrlSigner.urlOf(anyString())).thenAnswer(call -> URI.create("https://images.test/" + call.getArgument(0)));
        UUID account = UUID.fromString("5e1c0000-0000-4000-8000-000000000021");
        UUID device = UUID.fromString("5e1c0000-0000-4000-8000-000000000022");
        pairingService.pair(device, account, 1);
        detectionService.store(device, List.of(new NewDetection(
                UUID.fromString("5e1c0000-0000-4000-8000-000000000023"), "WA12345",
                OffsetDateTime.parse("2026-10-30T09:14:22.381Z"), 52.229676, 21.012229, 0.94, 0.88,
                "images/5e1c0000-0000-4000-8000-000000000022/2026/10/30/frame.jpg")));
        locationService.store(device, List.of(new NewDeviceLocation(UUID.randomUUID(),
                OffsetDateTime.parse("2026-10-30T09:15:00Z"), 52.23, 21.01)));

        mockMvc.perform(radialAnalysis(account))
                .andExpect(status().isOk())
                .andExpect(content().json(resource("detections/radial-analysis-response.json"), JsonCompareMode.STRICT));
    }

    /**
     * A valid request: centre, 500 m, one hour from FROM. Overrides come as name, value pairs and replace the default,
     * because param() would add a second value and the first one would be used.
     */
    private MockHttpServletRequestBuilder radialAnalysis(UUID account, String... overrides) {
        Map<String, String> params = new LinkedHashMap<>();
        params.put("lat", String.valueOf(LAT));
        params.put("lon", String.valueOf(LON));
        params.put("radiusMeters", "500");
        params.put("from", FROM.toString());
        params.put("to", TO.toString());
        for (int i = 0; i < overrides.length; i += 2) {
            params.put(overrides[i], overrides[i + 1]);
        }
        MockHttpServletRequestBuilder request = get(RADIAL_ANALYSIS).header(ACCOUNT_HEADER, account.toString());
        params.forEach(request::param);
        return request;
    }

    private UUID pairedDevice(UUID account) {
        UUID device = UUID.randomUUID();
        pairingService.pair(device, account, 1);
        return device;
    }

    /** An account has one paired device at a time: the old one is unpaired before the new one is paired. */
    private UUID replace(UUID oldDevice, UUID account) {
        pairingService.unpair(oldDevice, 2);
        return pairedDevice(account);
    }

    private void locate(UUID device, OffsetDateTime... times) {
        locationService.store(device, Arrays.stream(times)
                .map(time -> new NewDeviceLocation(UUID.randomUUID(), time, LAT, LON)).toList());
    }

    private static NewDetection detection(String plate, OffsetDateTime detectedAt, double lat) {
        return new NewDetection(UUID.randomUUID(), plate, detectedAt, lat, LON, 0.9, 0.8, "images/x.jpg");
    }

    private static String resource(String path) throws Exception {
        return new ClassPathResource(path).getContentAsString(StandardCharsets.UTF_8);
    }
}
