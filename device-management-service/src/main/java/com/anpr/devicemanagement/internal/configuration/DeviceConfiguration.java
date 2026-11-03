package com.anpr.devicemanagement.internal.configuration;

import lombok.Getter;
import lombok.Setter;
import software.amazon.awssdk.enhanced.dynamodb.extensions.annotations.DynamoDbVersionAttribute;
import software.amazon.awssdk.enhanced.dynamodb.mapper.annotations.DynamoDbBean;
import software.amazon.awssdk.enhanced.dynamodb.mapper.annotations.DynamoDbFlatten;
import software.amazon.awssdk.enhanced.dynamodb.mapper.annotations.DynamoDbPartitionKey;

import java.time.Instant;
import java.util.UUID;

/**
 * Operating configuration of one device (diagram: device_configurations), one item per device.
 * <p>
 * The key must match the table Terraform creates: partition key {@code deviceId} (string), no sort key. The settings
 * are stored as top-level attributes of the item. {@code version} is maintained by the DynamoDB mapper: every write
 * raises it and fails when the stored version differs (optimistic locking).
 */
@DynamoDbBean
@Getter
@Setter
public class DeviceConfiguration {

    private UUID deviceId;
    private Long version;
    private Instant updatedAt;
    private DeviceSettings settings;

    /** The configuration a new device starts with; {@code settings} must not be shared with another configuration. */
    public static DeviceConfiguration initial(UUID deviceId, DeviceSettings settings, Instant now) {
        DeviceConfiguration configuration = new DeviceConfiguration();
        configuration.deviceId = deviceId;
        configuration.settings = settings;
        configuration.updatedAt = now;
        return configuration;
    }

    public void replaceSettings(DeviceSettings settings, Instant now) {
        this.settings = settings;
        this.updatedAt = now;
    }

    @DynamoDbPartitionKey
    public UUID getDeviceId() {
        return deviceId;
    }

    @DynamoDbVersionAttribute
    public Long getVersion() {
        return version;
    }

    @DynamoDbFlatten
    public DeviceSettings getSettings() {
        return settings;
    }
}
