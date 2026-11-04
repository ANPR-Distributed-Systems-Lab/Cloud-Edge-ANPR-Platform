package com.anpr.devicemanagement.api.metrics;

import com.anpr.devicemanagement.support.ApiTestSupport;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;

import java.time.Instant;
import java.time.temporal.ChronoUnit;

import static org.hamcrest.Matchers.hasSize;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class DeviceMetricsIT extends ApiTestSupport {

    private static final Instant NOW = Instant.now().truncatedTo(ChronoUnit.SECONDS);

    @Test
    void theDeviceReportsAndItsOwnerChartsOldestFirst() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();

        report(owner, metric(NOW.minusSeconds(60)), metric(NOW.minusSeconds(180)), metric(NOW.minusSeconds(120)));

        mockMvc.perform(get("/api/v1/device/metrics").with(person(owner.accountId())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.deviceId").value(owner.deviceId().toString()))
                .andExpect(jsonPath("$.metrics", hasSize(3)))
                .andExpect(jsonPath("$.metrics[0].recordedAt").value(NOW.minusSeconds(180).toString()))
                .andExpect(jsonPath("$.metrics[2].recordedAt").value(NOW.minusSeconds(60).toString()))
                .andExpect(jsonPath("$.metrics[2].cpuTemperatureC").value(61.5))
                .andExpect(jsonPath("$.metrics[2].queues.detectionsPending").value(3))
                .andExpect(jsonPath("$.metrics[2].gps.fix").value("FIX_3D"));
    }

    @Test
    void limitAndBeforePageBackwards() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();
        report(owner, metric(NOW.minusSeconds(240)), metric(NOW.minusSeconds(180)), metric(NOW.minusSeconds(120)),
                metric(NOW.minusSeconds(60)));

        mockMvc.perform(get("/api/v1/device/metrics").with(person(owner.accountId()))
                        .param("limit", "2")
                        .param("before", NOW.minusSeconds(120).toString()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.metrics", hasSize(2)))
                .andExpect(jsonPath("$.metrics[0].recordedAt").value(NOW.minusSeconds(240).toString()))
                .andExpect(jsonPath("$.metrics[1].recordedAt").value(NOW.minusSeconds(180).toString()));
    }

    @Test
    void aRecentReportMakesTheDeviceOnline() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();
        mockMvc.perform(get("/api/v1/device").with(person(owner.accountId())))
                .andExpect(jsonPath("$.online").value(false))
                .andExpect(jsonPath("$.lastMetricsAt").isEmpty());

        report(owner, metric(NOW.minusSeconds(5)));

        mockMvc.perform(get("/api/v1/device").with(device(owner.deviceId())))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.online").value(true))
                .andExpect(jsonPath("$.lastMetricsAt").value(NOW.minusSeconds(5).toString()))
                .andExpect(jsonPath("$.username").value(owner.username()));
    }

    @Test
    void aBadBatchIsRefusedWholeWithTheIndexOfEveryProblem() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();

        mockMvc.perform(post("/api/v1/device/metrics").with(device(owner.deviceId()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(batch(metric(NOW.minusSeconds(10)), metric(NOW.plusSeconds(3600)), metric(NOW.minusSeconds(10)))))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"))
                .andExpect(jsonPath("$.fields", hasSize(2)))
                .andExpect(jsonPath("$.fields[0].index").value(1))
                .andExpect(jsonPath("$.fields[0].code").value("TIMESTAMP_IN_FUTURE"))
                .andExpect(jsonPath("$.fields[1].index").value(2))
                .andExpect(jsonPath("$.fields[1].code").value("DUPLICATE_RECORDED_AT"));

        mockMvc.perform(get("/api/v1/device/metrics").with(person(owner.accountId())))
                .andExpect(jsonPath("$.metrics", hasSize(0)));
    }

    @Test
    void aMissingFieldIsReportedWithTheIndexOfItsMeasurement() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();
        String withoutGps = metric(NOW).replace(", \"gps\": { \"fix\": \"FIX_3D\", \"satellites\": 9 }", "");

        mockMvc.perform(post("/api/v1/device/metrics").with(device(owner.deviceId()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(batch(metric(NOW.minusSeconds(60)), withoutGps)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.fields[0].index").value(1))
                .andExpect(jsonPath("$.fields[0].field").value("metrics[1].gps"))
                .andExpect(jsonPath("$.fields[0].code").value("REQUIRED"));
    }

    @Test
    void onlyTheDeviceReportsAndOnlyThePersonCharts() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();

        mockMvc.perform(post("/api/v1/device/metrics").with(person(owner.accountId()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(batch(metric(NOW))))
                .andExpect(status().isForbidden());
        mockMvc.perform(get("/api/v1/device/metrics").with(device(owner.deviceId())))
                .andExpect(status().isForbidden());
    }

    private void report(PersonWithDevice owner, String... metrics) throws Exception {
        mockMvc.perform(post("/api/v1/device/metrics").with(device(owner.deviceId()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(batch(metrics)))
                .andExpect(status().isNoContent());
    }

    private static String batch(String... metrics) {
        return "{ \"metrics\": [" + String.join(",", metrics) + "] }";
    }

    private static String metric(Instant recordedAt) {
        return """
                { "recordedAt": "%s", "cpuTemperatureC": 61.5, "cpuUsagePercent": 42.0, "ramUsagePercent": 55.0,
                  "processingFps": 2.0, "queues": { "detectionsPending": 3, "locationsPending": 10, "imagesPending": 1 },
                  "diskFreeMb": 12000, "uptimeSeconds": 3600, "gps": { "fix": "FIX_3D", "satellites": 9 } }
                """.formatted(recordedAt);
    }
}
