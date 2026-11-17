package com.anpr.devicemanagement.local;

import com.anpr.devicemanagement.internal.models.ModelReleases;
import com.anpr.devicemanagement.internal.provisioning.AccountDirectory;
import com.anpr.devicemanagement.internal.provisioning.DeviceEvents;
import com.anpr.devicemanagement.support.DynamoDbLocalSupport;
import com.jayway.jsonpath.JsonPath;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.system.CapturedOutput;
import org.springframework.boot.test.system.OutputCaptureExtension;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * The local profile as a developer runs it (application-local.yaml), with DynamoDB Local of the test run instead of
 * compose.yaml: the stand-ins replace Cognito and SNS, so a device can be created and used without AWS, and the
 * log is plain text with the trace id.
 */
@AutoConfigureMockMvc
@ActiveProfiles(value = "local", inheritProfiles = false)
@ExtendWith(OutputCaptureExtension.class)
class LocalProfileIT extends DynamoDbLocalSupport {

    @Autowired
    private MockMvc mockMvc;
    @Autowired
    private AccountDirectory accounts;
    @Autowired
    private DeviceEvents events;
    @Autowired
    private ModelReleases releases;

    @Test
    void usesTheLocalStandIns() {
        assertThat(accounts).isInstanceOf(LocalAccountDirectory.class);
        assertThat(events).isInstanceOf(LoggingDeviceEvents.class);
        assertThat(releases).isInstanceOf(LocalModelReleases.class);
    }

    @Test
    void aDeviceCanBeCreatedAndReadWithoutAwsAndTheLogIsPlainText(CapturedOutput output) throws Exception {
        UUID accountId = UUID.randomUUID();

        String created = mockMvc.perform(post("/api/v1/admin/devices")
                        .header("X-Trace-Id", "local-trace-1")
                        .header("X-Account-Type", "iam").header("X-Account-Id", "local-admin")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "accountId": "%s", "username": "rpi-local", "password": "Secret-password-1" }
                                """.formatted(accountId)))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();

        mockMvc.perform(get("/api/v1/device/config")
                        .header("X-Account-Type", "device").header("X-Account-Id", JsonPath.<String>read(created, "$.deviceId")))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.intervals.metricsSeconds").value(60));

        String eventLine = output.getOut().lines()
                .filter(line -> line.contains("Device event not published (local)"))
                .findFirst().orElseThrow();
        assertThat(eventLine).doesNotStartWith("{").contains("[local-trace-1]").contains("eventType=\"device.paired\"");
    }
}
