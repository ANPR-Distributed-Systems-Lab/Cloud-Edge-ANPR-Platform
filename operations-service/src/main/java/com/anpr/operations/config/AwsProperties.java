package com.anpr.operations.config;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

import java.time.Duration;

/**
 * AWS settings of the service, bound from {@code app.aws.*} (see application.yaml).
 * A missing required value fails the startup instead of the first message.
 *
 * @param region AWS region of the clients
 * @param sqs    queues this service consumes
 * @param s3     bucket of the detection photos
 */
@Validated
@ConfigurationProperties(prefix = "app.aws")
public record AwsProperties(@NotBlank String region, @Valid @NotNull Sqs sqs, @Valid @NotNull S3 s3) {

    /**
     * @param deviceEventsQueueUrl queue of the device.paired / device.unpaired events (docs/events/device-events.md)
     * @param eventsQueueUrl       queue of the edge events: detections and device locations (docs/api/ingest-*.md)
     */
    public record Sqs(@NotBlank String deviceEventsQueueUrl, @NotBlank String eventsQueueUrl) {
    }

    /**
     * @param imagesBucket     bucket the devices upload the photos to (keys under images/)
     * @param imageUrlValidity how long a presigned photo URL in a response may be used
     */
    public record S3(@NotBlank String imagesBucket, @NotNull Duration imageUrlValidity) {
    }
}
