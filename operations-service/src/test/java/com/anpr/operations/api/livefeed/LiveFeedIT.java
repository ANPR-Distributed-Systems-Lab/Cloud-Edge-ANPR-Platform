package com.anpr.operations.api.livefeed;

import com.anpr.operations.TestcontainersConfiguration;
import com.anpr.operations.internal.detections.DetectionService;
import com.anpr.operations.internal.detections.DetectionService.NewDetection;
import com.anpr.operations.internal.devices.DevicePairingService;
import com.anpr.operations.internal.locations.DeviceLocationService;
import com.anpr.operations.internal.locations.DeviceLocationService.NewDeviceLocation;
import com.anpr.operations.shared.storage.ImageUrlSigner;
import com.jayway.jsonpath.JsonPath;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.core.io.ClassPathResource;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.json.JsonCompareMode;
import org.springframework.test.web.servlet.MockMvc;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.UUID;
import java.util.stream.IntStream;

import static org.assertj.core.api.Assertions.assertThat;
import static org.hamcrest.Matchers.contains;
import static org.hamcrest.Matchers.empty;
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
class LiveFeedIT {
    private static final String ACCOUNT_HEADER = "X-Account-Id";
    private static final String LIVE_FEED = "/api/v1/detections/live-feed";
    private static final OffsetDateTime NOW = OffsetDateTime.of(2026, 10, 30, 9, 20, 0, 0, ZoneOffset.UTC);

    @Autowired private MockMvc mockMvc;
    @Autowired private DevicePairingService pairingService;
    @Autowired private DetectionService detectionService;
    @Autowired private DeviceLocationService locationService;
    @Autowired private JdbcTemplate jdbc;
    // The storing time is set by the database; the tests move it with SQL and pin "now" of the service instead.
    @MockitoBean private Clock clock;
    // Real signatures change every second; the contract test needs a stable URL. ImageUrlSignerTest covers signing.
    @MockitoBean private ImageUrlSigner imageUrlSigner;

    @BeforeEach
    void pinTheClock() {
        when(clock.instant()).thenReturn(NOW.toInstant());
        when(clock.getZone()).thenReturn(ZoneOffset.UTC);
    }

    @Test
    void returnsOnlyDetectionsOfTheCallerAccount() throws Exception {
        UUID account = UUID.randomUUID();
        store(pairedDevice(account), NOW.minusMinutes(1), detection("WA70001"));
        store(pairedDevice(UUID.randomUUID()), NOW.minusMinutes(1), detection("WA70002"));

        mockMvc.perform(get(LIVE_FEED).header(ACCOUNT_HEADER, account.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.detections[*].plate", contains("WA70001")));
    }

    @Test
    void nextPollReturnsOnlyDetectionsStoredAfterTheCursor() throws Exception {
        UUID account = UUID.randomUUID();
        UUID device = pairedDevice(account);
        store(device, NOW.minusMinutes(10), detection("WA70011"));
        String cursor = poll(account, null).cursor();

        store(device, NOW.minusMinutes(1), detection("WA70012"));

        mockMvc.perform(get(LIVE_FEED).param("cursor", cursor).header(ACCOUNT_HEADER, account.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.detections[*].plate", contains("WA70012")))
                .andExpect(jsonPath("$.hasMore").value(false));
    }

    @Test
    void aDetectionDeliveredLateWithAnOldDetectionTimeIsNotSkipped() throws Exception {
        UUID account = UUID.randomUUID();
        UUID device = pairedDevice(account);
        store(device, NOW.minusMinutes(5), detection("WA70021", NOW.minusMinutes(5)));
        String cursor = poll(account, null).cursor();

        // Buffered on the device for an hour, stored now: older detectedAt than what the client already has.
        store(device, NOW.minusMinutes(1), detection("WA70022", NOW.minusMinutes(60)));

        assertThat(poll(account, cursor).plates()).containsExactly("WA70022");
    }

    @Test
    void aBatchSharingOneStoringTimeIsSplitAcrossPagesWithoutGapsOrDuplicates() throws Exception {
        UUID account = UUID.randomUUID();
        UUID device = pairedDevice(account);
        store(device, NOW.minusMinutes(10), detection("WA70031"));
        String cursor = poll(account, null).cursor();

        NewDetection[] batch = IntStream.range(0, 70).mapToObj(i -> detection("WA70032")).toArray(NewDetection[]::new);
        store(device, NOW.minusMinutes(1), batch);

        Poll first = poll(account, cursor);
        Poll second = poll(account, first.cursor());

        assertThat(first.ids()).hasSize(50);
        assertThat(first.hasMore()).isTrue();
        assertThat(second.ids()).hasSize(20);
        assertThat(second.hasMore()).isFalse();
        Set<String> returned = new HashSet<>(first.ids());
        returned.addAll(second.ids());
        assertThat(returned).containsExactlyInAnyOrderElementsOf(
                Arrays.stream(batch).map(d -> d.detectionId().toString()).toList());
    }

    @Test
    void detectionsStoredInTheLastTwoSecondsWaitForTheNextPoll() throws Exception {
        UUID account = UUID.randomUUID();
        UUID device = pairedDevice(account);
        store(device, NOW.minusSeconds(10), detection("WA70041"));
        NewDetection fresh = detection("WA70042");
        store(device, NOW.minusSeconds(1), fresh);

        Poll first = poll(account, null);
        assertThat(first.plates()).containsExactly("WA70041");

        // The poll a few seconds later: the same detection is now older than two seconds.
        setStoredAt(fresh, NOW.minusSeconds(3));
        assertThat(poll(account, first.cursor()).plates()).containsExactly("WA70042");
    }

    @Test
    void firstPollReturnsTheFiftyMostRecentlyStoredInTheOrderTheyWereStored() throws Exception {
        UUID account = UUID.randomUUID();
        UUID device = pairedDevice(account);
        for (int minute = 55; minute >= 1; minute--) {
            store(device, NOW.minusMinutes(minute), detection("WA7%04d".formatted(minute)));
        }

        Poll first = poll(account, null);

        assertThat(first.plates()).hasSize(50);
        assertThat(first.plates().getFirst()).isEqualTo("WA70050");
        assertThat(first.plates().getLast()).isEqualTo("WA70001");
        assertThat(first.hasMore()).isFalse();
    }

    @Test
    void anAccountWithNoDetectionsGetsACursorThatCatchesTheFirstOne() throws Exception {
        UUID account = UUID.randomUUID();
        UUID device = pairedDevice(account);
        Poll empty = poll(account, null);
        assertThat(empty.plates()).isEmpty();

        store(device, NOW.plusSeconds(1), detection("WA70061"));
        when(clock.instant()).thenReturn(NOW.plusSeconds(10).toInstant());

        assertThat(poll(account, empty.cursor()).plates()).containsExactly("WA70061");
    }

    @Test
    void theRouteHasOnlyThePointsOfTheWindowAndTheLatestPosition() throws Exception {
        UUID account = UUID.randomUUID();
        UUID device = pairedDevice(account);
        locate(device, NOW.minusMinutes(30), NOW.minusMinutes(10), NOW.minusMinutes(1));

        mockMvc.perform(get(LIVE_FEED).param("windowMinutes", "20").header(ACCOUNT_HEADER, account.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.devices[0].deviceId").value(device.toString()))
                .andExpect(jsonPath("$.devices[0].track[*].recordedAt",
                        contains("2026-10-30T09:10:00Z", "2026-10-30T09:19:00Z")))
                .andExpect(jsonPath("$.devices[0].lastSeenAt").value("2026-10-30T09:19:00Z"));
    }

    @Test
    void aDeviceSilentForTheWholeWindowStaysOnTheMapAtItsLastPosition() throws Exception {
        UUID account = UUID.randomUUID();
        UUID device = pairedDevice(account);
        locate(device, NOW.minusHours(3));

        mockMvc.perform(get(LIVE_FEED).param("windowMinutes", "20").header(ACCOUNT_HEADER, account.toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.devices[0].track", empty()))
                .andExpect(jsonPath("$.devices[0].lastSeenAt").value("2026-10-30T06:20:00Z"));
    }

    @Test
    void anAccountWithoutAPairedDeviceHasNoDevices() throws Exception {
        mockMvc.perform(get(LIVE_FEED).header(ACCOUNT_HEADER, UUID.randomUUID().toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.devices", empty()))
                .andExpect(jsonPath("$.detections", empty()));
    }

    @Test
    void aCursorThatIsNotOursReturns400() throws Exception {
        mockMvc.perform(get(LIVE_FEED).param("cursor", "garbage!").header(ACCOUNT_HEADER, UUID.randomUUID().toString()))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"));
    }

    @Test
    void aWindowLongerThanAnHourReturns400() throws Exception {
        mockMvc.perform(get(LIVE_FEED).param("windowMinutes", "61").header(ACCOUNT_HEADER, UUID.randomUUID().toString()))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"));
    }

    @Test
    void responseHasTheShapeOfTheContract() throws Exception {
        when(imageUrlSigner.urlOf(anyString())).thenAnswer(call -> URI.create("https://images.test/" + call.getArgument(0)));
        UUID account = UUID.fromString("5e1c0000-0000-4000-8000-000000000011");
        UUID device = UUID.fromString("5e1c0000-0000-4000-8000-000000000012");
        pairingService.pair(device, account, 1);
        store(device, OffsetDateTime.parse("2026-10-30T09:19:00Z"), new NewDetection(
                UUID.fromString("5e1c0000-0000-4000-8000-000000000013"), "WA12345",
                OffsetDateTime.parse("2026-10-30T09:14:22.381Z"), 52.229676, 21.012229, 0.94, 0.88,
                "images/5e1c0000-0000-4000-8000-000000000012/2026/10/30/frame.jpg"));
        locationService.store(device, List.of(new NewDeviceLocation(UUID.randomUUID(),
                OffsetDateTime.parse("2026-10-30T09:15:00Z"), 52.23, 21.01)));

        mockMvc.perform(get(LIVE_FEED).header(ACCOUNT_HEADER, account.toString()))
                .andExpect(status().isOk())
                .andExpect(content().json(resource("livefeed/live-feed-response.json"), JsonCompareMode.STRICT));
    }

    private record Poll(List<String> ids, List<String> plates, String cursor, boolean hasMore) {
    }

    private Poll poll(UUID account, String cursor) throws Exception {
        var request = get(LIVE_FEED).header(ACCOUNT_HEADER, account.toString());
        if (cursor != null) {
            request = request.param("cursor", cursor);
        }
        String body = mockMvc.perform(request).andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString();
        return new Poll(JsonPath.read(body, "$.detections[*].detectionId"), JsonPath.read(body, "$.detections[*].plate"),
                JsonPath.read(body, "$.nextCursor"), JsonPath.read(body, "$.hasMore"));
    }

    private UUID pairedDevice(UUID account) {
        UUID device = UUID.randomUUID();
        pairingService.pair(device, account, 1);
        return device;
    }

    /** Stores like the queue consumer does, then sets the storing time the test needs. */
    private void store(UUID device, OffsetDateTime storedAt, NewDetection... detections) {
        detectionService.store(device, List.of(detections));
        for (NewDetection detection : detections) {
            setStoredAt(detection, storedAt);
        }
    }

    private void setStoredAt(NewDetection detection, OffsetDateTime storedAt) {
        jdbc.update("UPDATE detections SET ingested_at = ? WHERE detection_id = ?", storedAt, detection.detectionId());
    }

    private void locate(UUID device, OffsetDateTime... times) {
        List<NewDeviceLocation> points = new ArrayList<>();
        for (OffsetDateTime time : times) {
            points.add(new NewDeviceLocation(UUID.randomUUID(), time, 52.2, 21.0));
        }
        locationService.store(device, points);
    }

    private static NewDetection detection(String plate) {
        return detection(plate, NOW.minusMinutes(1));
    }

    private static NewDetection detection(String plate, OffsetDateTime detectedAt) {
        return new NewDetection(UUID.randomUUID(), plate, detectedAt, 52.2, 21.0, 0.9, 0.8, "images/x.jpg");
    }

    private static String resource(String path) throws Exception {
        return new ClassPathResource(path).getContentAsString(StandardCharsets.UTF_8);
    }
}
