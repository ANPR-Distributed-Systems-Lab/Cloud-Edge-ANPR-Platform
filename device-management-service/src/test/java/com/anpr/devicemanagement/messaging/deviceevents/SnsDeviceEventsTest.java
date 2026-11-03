package com.anpr.devicemanagement.messaging.deviceevents;

import com.anpr.devicemanagement.config.AwsProperties;
import com.anpr.devicemanagement.shared.tracing.TraceId;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.slf4j.MDC;
import software.amazon.awssdk.services.sns.SnsClient;
import software.amazon.awssdk.services.sns.model.PublishRequest;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.verify;

@ExtendWith(MockitoExtension.class)
class SnsDeviceEventsTest {

    private static final String TOPIC = "arn:aws:sns:eu-central-1:000000000000:device-events";
    private static final UUID DEVICE_ID = UUID.fromString("7d3f2c1e-0000-4000-8000-000000000000");
    private static final UUID ACCOUNT_ID = UUID.fromString("d1c2a0f8-0000-4000-8000-000000000000");

    @Mock
    private SnsClient sns;

    private final JsonMapper jsonMapper = JsonMapper.builder().build();
    private SnsDeviceEvents events;

    @BeforeEach
    void setUp() {
        AwsProperties aws = new AwsProperties("eu-central-1", null, null, null, new AwsProperties.Sns(TOPIC));
        events = new SnsDeviceEvents(sns, aws, jsonMapper, Clock.fixed(Instant.parse("2026-11-01T10:00:00Z"), ZoneOffset.UTC));
        MDC.put(TraceId.MDC_KEY, "trace-1");
    }

    @AfterEach
    void tearDown() {
        MDC.remove(TraceId.MDC_KEY);
    }

    @Test
    void pairedCarriesTheOwnerAndTheAttributes() {
        events.paired(DEVICE_ID, ACCOUNT_ID, 1);

        PublishRequest request = published();
        JsonNode body = jsonMapper.readTree(request.message());
        assertThat(request.topicArn()).isEqualTo(TOPIC);
        assertThat(body.get("eventId").asString()).hasSize(36);
        assertThat(body.get("occurredAt").asString()).isEqualTo("2026-11-01T10:00:00.000Z");
        assertThat(body.get("version").asLong()).isEqualTo(1);
        assertThat(body.get("deviceId").asString()).isEqualTo(DEVICE_ID.toString());
        assertThat(body.get("accountId").asString()).isEqualTo(ACCOUNT_ID.toString());
        assertThat(request.messageAttributes().get("eventType").stringValue()).isEqualTo("device.paired");
        assertThat(request.messageAttributes().get("traceId").stringValue()).isEqualTo("trace-1");
    }

    @Test
    void unpairedHasNoOwner() {
        events.unpaired(DEVICE_ID, 2);

        PublishRequest request = published();
        JsonNode body = jsonMapper.readTree(request.message());
        assertThat(body.has("accountId")).isFalse();
        assertThat(body.get("version").asLong()).isEqualTo(2);
        assertThat(request.messageAttributes().get("eventType").stringValue()).isEqualTo("device.unpaired");
    }

    private PublishRequest published() {
        ArgumentCaptor<PublishRequest> request = ArgumentCaptor.forClass(PublishRequest.class);
        verify(sns).publish(request.capture());
        return request.getValue();
    }
}
