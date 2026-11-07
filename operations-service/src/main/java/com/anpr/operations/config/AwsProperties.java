package com.anpr.operations.config;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

/**
 * AWS settings of the service, bound from {@code app.aws.*} (see application.yaml).
 * A missing required value fails the startup instead of the first message.
 *
 * @param region AWS region of the clients
 * @param sqs    queues this service consumes
 */
@Validated
@ConfigurationProperties(prefix = "app.aws")
public record AwsProperties(@NotBlank String region, @Valid @NotNull Sqs sqs) {

    /**
     * @param deviceEventsQueueUrl queue of the device.paired / device.unpaired events (docs/events/device-events.md)
     * @param eventsQueueUrl       queue of the edge events: detections and device locations (docs/api/ingest-*.md)
     */
    public record Sqs(@NotBlank String deviceEventsQueueUrl, @NotBlank String eventsQueueUrl) {
    }
}
