package com.anpr.devicemanagement.internal.metrics;

import lombok.Getter;
import lombok.Setter;
import software.amazon.awssdk.enhanced.dynamodb.mapper.annotations.DynamoDbBean;
import software.amazon.awssdk.enhanced.dynamodb.mapper.annotations.DynamoDbConvertedBy;
import software.amazon.awssdk.enhanced.dynamodb.mapper.annotations.DynamoDbPartitionKey;
import software.amazon.awssdk.enhanced.dynamodb.mapper.annotations.DynamoDbSortKey;

import java.time.Duration;
import java.time.Instant;
import java.util.UUID;

/**
 * One health measurement of a device (View 5; table device-metrics, diagram: device_statuses). A device's history is
 * all items with its deviceId, ordered by the moment of the measurement.
 * <p>
 * The keys must match the table Terraform creates: partition key {@code deviceId} (string) and sort key
 * {@code recordedAt} (number, epoch milliseconds). DynamoDB deletes an item after {@code expiresAt} (epoch seconds,
 * table TTL).
 */
@DynamoDbBean
@Getter
@Setter
public class Measurement {

    private UUID deviceId;
    private Instant recordedAt;
    private Long expiresAt;

    private Double cpuTemperatureC;
    private Double cpuUsagePercent;
    private Double ramUsagePercent;
    private Double processingFps;
    private QueueLengths queues;
    private Long diskFreeMb;
    private Long uptimeSeconds;
    private GpsStatus gps;

    /** Assigns the measurement to its device and sets when DynamoDB may delete it. */
    public void storeFor(UUID deviceId, Duration retention) {
        this.deviceId = deviceId;
        this.expiresAt = recordedAt.plus(retention).getEpochSecond();
    }

    @DynamoDbPartitionKey
    public UUID getDeviceId() {
        return deviceId;
    }

    @DynamoDbSortKey
    @DynamoDbConvertedBy(EpochMillisConverter.class)
    public Instant getRecordedAt() {
        return recordedAt;
    }

    /** Items waiting on the device to be sent (store-and-forward). */
    @DynamoDbBean
    @Getter
    @Setter
    public static class QueueLengths {
        private Integer detectionsPending;
        private Integer locationsPending;
        private Integer imagesPending;
    }

    @DynamoDbBean
    @Getter
    @Setter
    public static class GpsStatus {
        private GpsFix fix;
        private Integer satellites;
    }

    public enum GpsFix {
        NONE, FIX_2D, FIX_3D
    }
}
