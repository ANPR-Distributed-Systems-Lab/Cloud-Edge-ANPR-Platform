package com.anpr.devicemanagement.messaging.deviceevents;

import com.anpr.devicemanagement.config.AwsProperties;
import com.anpr.devicemanagement.internal.provisioning.DeviceEvents;
import com.anpr.devicemanagement.shared.tracing.TraceId;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;
import software.amazon.awssdk.services.sns.SnsClient;
import software.amazon.awssdk.services.sns.model.MessageAttributeValue;
import software.amazon.awssdk.services.sns.model.PublishRequest;
import tools.jackson.databind.json.JsonMapper;

import java.time.Clock;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.util.Map;
import java.util.UUID;

/**
 * Publishes the device events to SNS: the JSON body plus the attributes {@code eventType} (subscriptions filter on it)
 * and {@code traceId} (of the request that caused the change).
 */
@Slf4j
@Component
@Profile("!local")
public class SnsDeviceEvents implements DeviceEvents {
    static final String PAIRED = "device.paired";
    static final String UNPAIRED = "device.unpaired";

    /** RFC 3339 UTC with milliseconds, as in the example of the event documentation. */
    private static final DateTimeFormatter OCCURRED_AT =
            DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'").withZone(ZoneOffset.UTC);

    private final SnsClient sns;
    private final String topicArn;
    private final JsonMapper jsonMapper;
    private final Clock clock;

    public SnsDeviceEvents(SnsClient sns, AwsProperties aws, JsonMapper jsonMapper, Clock clock) {
        this.sns = sns;
        this.topicArn = aws.sns().deviceEventsTopicArn();
        this.jsonMapper = jsonMapper;
        this.clock = clock;
    }

    @Override
    public void paired(UUID deviceId, UUID accountId, long version) {
        publish(PAIRED, deviceId, accountId.toString(), version);
    }

    @Override
    public void unpaired(UUID deviceId, long version) {
        publish(UNPAIRED, deviceId, null, version);
    }

    private void publish(String eventType, UUID deviceId, String accountId, long version) {
        String eventId = UUID.randomUUID().toString();
        DeviceEventMessage message = new DeviceEventMessage(eventId, OCCURRED_AT.format(clock.instant()), version,
                deviceId.toString(), accountId);

        sns.publish(PublishRequest.builder()
                .topicArn(topicArn)
                .message(jsonMapper.writeValueAsString(message))
                .messageAttributes(Map.of(
                        "eventType", stringAttribute(eventType),
                        "traceId", stringAttribute(traceId())))
                .build());

        log.atInfo().addKeyValue("eventType", eventType).addKeyValue("eventId", eventId)
                .addKeyValue("deviceId", deviceId).addKeyValue("version", version)
                .log("Device event published");
    }

    /** Events are published while handling a request, which always has a trace id; anything else is a bug. */
    private static String traceId() {
        return TraceId.current().orElseGet(() -> {
            String generated = UUID.randomUUID().toString();
            log.atWarn().addKeyValue("traceId", generated).log("No trace id in the context, generated one");
            return generated;
        });
    }

    private static MessageAttributeValue stringAttribute(String value) {
        return MessageAttributeValue.builder().dataType("String").stringValue(value).build();
    }
}
