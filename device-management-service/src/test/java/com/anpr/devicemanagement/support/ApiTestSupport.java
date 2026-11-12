package com.anpr.devicemanagement.support;

import com.anpr.devicemanagement.internal.models.ModelName;
import com.anpr.devicemanagement.internal.models.ModelRelease;
import com.anpr.devicemanagement.internal.models.ModelReleases;
import com.anpr.devicemanagement.internal.provisioning.AccountDirectory;
import com.anpr.devicemanagement.internal.provisioning.DeviceEvents;
import com.jayway.jsonpath.JsonPath;
import org.junit.jupiter.api.BeforeEach;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.RequestPostProcessor;

import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Base of the API tests: the whole application over MockMvc with DynamoDB Local. Cognito, SNS and the models bucket
 * are replaced by mocks of their ports (the adapters have their own unit tests); every model version counts as
 * published unless a test says otherwise. The identity headers are set as API Gateway sets them.
 */
@AutoConfigureMockMvc
public abstract class ApiTestSupport extends DynamoDbLocalSupport {

    static {
        // The presigner signs with credentials from the default chain; fixed ones keep the tests off any real account.
        System.setProperty("aws.accessKeyId", "test");
        System.setProperty("aws.secretAccessKey", "test");
    }

    @Autowired
    protected MockMvc mockMvc;
    @MockitoBean
    protected AccountDirectory accounts;
    @MockitoBean
    protected DeviceEvents events;
    @MockitoBean
    protected ModelReleases releases;

    @BeforeEach
    void everyModelVersionIsPublished() {
        when(releases.find(any(), anyString())).thenAnswer(call -> Optional.of(
                release(call.getArgument(0), call.getArgument(1))));
    }

    protected static ModelRelease release(ModelName model, String version) {
        return new ModelRelease(model.id(), version, List.of(new ModelRelease.File("model.onnx", "a".repeat(64), 1234)));
    }

    protected static RequestPostProcessor person(UUID accountId) {
        return identity("user", accountId.toString());
    }

    protected static RequestPostProcessor device(UUID deviceId) {
        return identity("device", deviceId.toString());
    }

    protected static RequestPostProcessor administrator() {
        return identity("iam", "arn:aws:sts::000000000000:assumed-role/Admin/tester");
    }

    /** A new person with a new device, created through the admin endpoint. */
    protected PersonWithDevice createPersonWithDevice() throws Exception {
        UUID accountId = UUID.randomUUID();
        UUID deviceId = UUID.randomUUID();
        String username = "rpi-" + deviceId.toString().substring(0, 8);
        when(accounts.isPerson(accountId)).thenReturn(true);
        when(accounts.createDevice(eq(username), anyString())).thenReturn(deviceId);

        String body = mockMvc.perform(post("/api/v1/admin/devices").with(administrator())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(createDeviceRequest(accountId, username)))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
        return new PersonWithDevice(accountId, UUID.fromString(JsonPath.read(body, "$.deviceId")), username);
    }

    protected static String createDeviceRequest(UUID accountId, String username) {
        return """
                { "accountId": "%s", "username": "%s", "password": "Secret-password-1" }
                """.formatted(accountId, username);
    }

    private static RequestPostProcessor identity(String type, String id) {
        return request -> {
            request.addHeader("X-Account-Type", type);
            request.addHeader("X-Account-Id", id);
            return request;
        };
    }

    public record PersonWithDevice(UUID accountId, UUID deviceId, String username) {
    }
}
