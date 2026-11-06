package com.anpr.operations.api.alerts;

import com.anpr.operations.TestcontainersConfiguration;
import com.anpr.operations.internal.devices.DevicePairingService;
import com.jayway.jsonpath.JsonPath;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;

import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.UUID;

import static org.hamcrest.Matchers.containsInAnyOrder;
import static org.hamcrest.Matchers.matchesPattern;
import static org.hamcrest.Matchers.not;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@Import(TestcontainersConfiguration.class)
class AlertsControllerIT {

    private static final String ACCOUNT_HEADER = "X-Account-Id";
    private static final String ACCOUNT_TYPE_HEADER = "X-Account-Type";

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private DevicePairingService pairingService;

    @Test
    void createAlertReturns201() throws Exception {
        String account = UUID.randomUUID().toString();

        mockMvc.perform(post("/api/v1/alerts")
                        .header(ACCOUNT_HEADER, account)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "plate": "WA12345", "alertText": "Stolen" }
                                """))
                .andExpect(status().isCreated())
                .andExpect(header().exists("Location"))
                .andExpect(jsonPath("$.plate").value("WA12345"))
                .andExpect(jsonPath("$.version").value(0));
    }

    @Test
    void duplicatePlateReturns409() throws Exception {
        String account = UUID.randomUUID().toString();
        createAlert(account, "KR98765");

        mockMvc.perform(post("/api/v1/alerts")
                        .header(ACCOUNT_HEADER, account)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "plate": "KR98765" }
                                """))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("ALERT_ALREADY_EXISTS"))
                .andExpect(jsonPath("$.requestId").exists());
    }

    @Test
    void anErrorCarriesTheTraceIdOfTheRequest() throws Exception {
        mockMvc.perform(get("/api/v1/alerts/{alertId}", UUID.randomUUID())
                        .header(ACCOUNT_HEADER, UUID.randomUUID().toString())
                        .header("X-Trace-Id", "trace-abc-1"))
                .andExpect(status().isNotFound())
                .andExpect(header().string("X-Trace-Id", "trace-abc-1"))
                .andExpect(jsonPath("$.requestId").value("trace-abc-1"));
    }

    @Test
    void invalidPlateReturns400() throws Exception {
        mockMvc.perform(post("/api/v1/alerts")
                        .header(ACCOUNT_HEADER, UUID.randomUUID().toString())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "plate": "wa 12" }
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"))
                .andExpect(jsonPath("$.fields[0].field").value("plate"))
                .andExpect(jsonPath("$.fields[0].code").value("PATTERN"));
    }

    @Test
    void alertOfAnotherAccountReturns404() throws Exception {
        String alertId = createAlert(UUID.randomUUID().toString(), "GD11111");

        mockMvc.perform(get("/api/v1/alerts/{id}", alertId)
                        .header(ACCOUNT_HEADER, UUID.randomUUID().toString()))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("ALERT_NOT_FOUND"));
    }

    @Test
    void updateWithStaleVersionReturns409() throws Exception {
        String account = UUID.randomUUID().toString();
        String alertId = createAlert(account, "PO55555");

        mockMvc.perform(put("/api/v1/alerts/{id}", alertId)
                        .header(ACCOUNT_HEADER, account)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "alertText": "Changed", "version": 7 }
                                """))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("CONCURRENT_MODIFICATION"));
    }

    @Test
    void updateChangesTheTextAndNeverThePlate() throws Exception {
        String account = UUID.randomUUID().toString();
        String alertId = createAlert(account, "LU22222");

        mockMvc.perform(put("/api/v1/alerts/{id}", alertId)
                        .header(ACCOUNT_HEADER, account)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "plate": "LU33333", "alertText": "Changed", "version": 0 }
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.plate").value("LU22222"))
                .andExpect(jsonPath("$.alertText").value("Changed"));
    }

    @Test
    void deviceGetsAllAlertsOfItsOwnerWithAnETag() throws Exception {
        String owner = UUID.randomUUID().toString();
        String device = pairedDevice(owner);
        // More than the default page size of a person, so a device must get them all at once.
        for (int i = 0; i < 25; i++) {
            createAlert(owner, "DV%05d".formatted(i));
        }
        createAlert(UUID.randomUUID().toString(), "DV99999");

        mockMvc.perform(alertsOfDevice(device))
                .andExpect(status().isOk())
                .andExpect(header().string("ETag", matchesPattern("W/\"[0-9a-f]{32}\"")))
                .andExpect(jsonPath("$.items.length()").value(25))
                .andExpect(jsonPath("$.page.totalElements").value(25));
    }

    @Test
    void deviceGetsNotModifiedWhileTheListIsUnchanged() throws Exception {
        String owner = UUID.randomUUID().toString();
        String device = pairedDevice(owner);
        createAlert(owner, "NM10001");
        String eTag = mockMvc.perform(alertsOfDevice(device))
                .andReturn().getResponse().getHeader("ETag");

        mockMvc.perform(alertsOfDevice(device).header("If-None-Match", eTag))
                .andExpect(status().isNotModified())
                .andExpect(header().string("ETag", eTag))
                .andExpect(content().string(""));
    }

    @Test
    void updatedAlertGivesTheDeviceANewList() throws Exception {
        String owner = UUID.randomUUID().toString();
        String device = pairedDevice(owner);
        String alertId = createAlert(owner, "UP10001");
        String eTag = mockMvc.perform(alertsOfDevice(device))
                .andReturn().getResponse().getHeader("ETag");

        mockMvc.perform(put("/api/v1/alerts/{id}", alertId)
                        .header(ACCOUNT_HEADER, owner)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "alertText": "Changed", "version": 0 }
                                """))
                .andExpect(status().isOk());

        mockMvc.perform(alertsOfDevice(device).header("If-None-Match", eTag))
                .andExpect(status().isOk())
                .andExpect(header().string("ETag", not(eTag)))
                .andExpect(jsonPath("$.items[0].alertText").value("Changed"));
    }

    @Test
    void deviceWithNoOwnerReturns403() throws Exception {
        mockMvc.perform(alertsOfDevice(UUID.randomUUID().toString()))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value("DEVICE_NOT_PAIRED"))
                .andExpect(jsonPath("$.requestId").exists());

        String owner = UUID.randomUUID().toString();
        String device = pairedDevice(owner);
        pairingService.unpair(UUID.fromString(device), 2);

        mockMvc.perform(alertsOfDevice(device))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value("DEVICE_NOT_PAIRED"));
    }

    @Test
    void missingAccountHeaderReturns401() throws Exception {
        mockMvc.perform(get("/api/v1/alerts"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("UNAUTHENTICATED"));
    }

    @Test
    void listReturnsOnlyAlertsOfCurrentAccount() throws Exception {
        String account = UUID.randomUUID().toString();
        String otherAccount = UUID.randomUUID().toString();
        createAlert(account, "WA10001");
        createAlert(account, "WA10002");
        createAlert(otherAccount, "WA10003");

        mockMvc.perform(get("/api/v1/alerts")
                        .header(ACCOUNT_HEADER, account))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(2))
                .andExpect(jsonPath("$.items[*].plate", containsInAnyOrder("WA10001", "WA10002")))
                .andExpect(jsonPath("$.page.totalElements").value(2))
                .andExpect(header().doesNotExist("ETag"));
    }

    @Test
    void listFiltersByPlatePrefix() throws Exception {
        String account = UUID.randomUUID().toString();
        createAlert(account, "WA10001");
        createAlert(account, "WA20002");
        createAlert(account, "KR10003");

        mockMvc.perform(get("/api/v1/alerts")
                        .param("plate", "WA1")
                        .header(ACCOUNT_HEADER, account))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items[*].plate", containsInAnyOrder("WA10001")))
                .andExpect(jsonPath("$.page.totalElements").value(1));
    }

    @Test
    void listFiltersByCreationTimeRange() throws Exception {
        String account = UUID.randomUUID().toString();
        createAlert(account, "GD50005");
        OffsetDateTime now = OffsetDateTime.now(ZoneOffset.UTC);

        mockMvc.perform(get("/api/v1/alerts")
                        .param("from", now.minusHours(1).toString())
                        .param("to", now.plusHours(1).toString())
                        .header(ACCOUNT_HEADER, account))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.page.totalElements").value(1));

        mockMvc.perform(get("/api/v1/alerts")
                        .param("from", now.plusHours(1).toString())
                        .header(ACCOUNT_HEADER, account))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.page.totalElements").value(0));

        mockMvc.perform(get("/api/v1/alerts")
                        .param("to", now.minusHours(1).toString())
                        .header(ACCOUNT_HEADER, account))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.page.totalElements").value(0));
    }

    @Test
    void listWithToBeforeFromReturns400() throws Exception {
        mockMvc.perform(get("/api/v1/alerts")
                        .param("from", "2026-10-02T00:00:00Z")
                        .param("to", "2026-10-01T00:00:00Z")
                        .header(ACCOUNT_HEADER, UUID.randomUUID().toString()))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_TIME_RANGE"))
                .andExpect(jsonPath("$.requestId").exists());
    }

    @Test
    void getReturnsAlert() throws Exception {
        String account = UUID.randomUUID().toString();
        String alertId = createAlert(account, "LU20002");

        mockMvc.perform(get("/api/v1/alerts/{id}", alertId)
                        .header(ACCOUNT_HEADER, account))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.alertId").value(alertId))
                .andExpect(jsonPath("$.plate").value("LU20002"));
    }

    @Test
    void updateChangesAlertAndIncrementsVersion() throws Exception {
        String account = UUID.randomUUID().toString();
        String alertId = createAlert(account, "SK30003");

        mockMvc.perform(put("/api/v1/alerts/{id}", alertId)
                        .header(ACCOUNT_HEADER, account)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "alertText": "Changed", "version": 0 }
                                """))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.plate").value("SK30003"))
                .andExpect(jsonPath("$.alertText").value("Changed"))
                .andExpect(jsonPath("$.version").value(1));
    }

    @Test
    void deleteRemovesAlert() throws Exception {
        String account = UUID.randomUUID().toString();
        String alertId = createAlert(account, "BI40004");

        mockMvc.perform(delete("/api/v1/alerts/{id}", alertId)
                        .header(ACCOUNT_HEADER, account))
                .andExpect(status().isNoContent());

        mockMvc.perform(get("/api/v1/alerts/{id}", alertId)
                        .header(ACCOUNT_HEADER, account))
                .andExpect(status().isNotFound());
    }

    private String createAlert(String account, String plate) throws Exception {
        String body = mockMvc.perform(post("/api/v1/alerts")
                        .header(ACCOUNT_HEADER, account)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{ \"plate\": \"" + plate + "\" }"))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
        return JsonPath.read(body, "$.alertId");
    }

    private String pairedDevice(String owner) {
        UUID device = UUID.randomUUID();
        pairingService.pair(device, UUID.fromString(owner), 1);
        return device.toString();
    }

    private static MockHttpServletRequestBuilder alertsOfDevice(String device) {
        return get("/api/v1/alerts")
                .header(ACCOUNT_HEADER, device)
                .header(ACCOUNT_TYPE_HEADER, "device");
    }
}