package com.anpr.devicemanagement.internal.status;

import software.amazon.awssdk.enhanced.dynamodb.mapper.annotations.DynamoDbBean;
import software.amazon.awssdk.enhanced.dynamodb.mapper.annotations.DynamoDbPartitionKey;
import software.amazon.awssdk.enhanced.dynamodb.mapper.annotations.DynamoDbSortKey;

/**
 * One heartbeat of a device (diagram: device_statuses). A device's history is all items with
 * its deviceId, ordered by reportedAt.
 * <p>
 * The keys must match the table Terraform creates: partition key {@code deviceId} (string) and
 * sort key {@code reportedAt} (number). The metrics (connection state, local queues, FPS, CPU,
 * RAM) are added together with the API contract.
 */
@DynamoDbBean
public class DeviceStatus {

    private String deviceId;

    /** Epoch milliseconds (UTC). A number, so a device's heartbeats sort chronologically. */
    private Long reportedAt;

    /** Epoch seconds after which DynamoDB deletes the item (table TTL); null keeps it forever. */
    private Long expiresAt;

    @DynamoDbPartitionKey
    public String getDeviceId() {
        return deviceId;
    }

    public void setDeviceId(String deviceId) {
        this.deviceId = deviceId;
    }

    @DynamoDbSortKey
    public Long getReportedAt() {
        return reportedAt;
    }

    public void setReportedAt(Long reportedAt) {
        this.reportedAt = reportedAt;
    }

    public Long getExpiresAt() {
        return expiresAt;
    }

    public void setExpiresAt(Long expiresAt) {
        this.expiresAt = expiresAt;
    }
}
