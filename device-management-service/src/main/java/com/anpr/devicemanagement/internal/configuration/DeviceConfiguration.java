package com.anpr.devicemanagement.internal.configuration;

import software.amazon.awssdk.enhanced.dynamodb.mapper.annotations.DynamoDbBean;
import software.amazon.awssdk.enhanced.dynamodb.mapper.annotations.DynamoDbPartitionKey;

/**
 * Operating configuration of one device (diagram: device_configurations), one item per device.
 * <p>
 * The key must match the table Terraform creates: partition key {@code deviceId} (string), no sort key.
 * The configuration attributes (plate cooldown, batching, ML model parameters, polling frequency)
 * are added together with the API contract.
 */
@DynamoDbBean
public class DeviceConfiguration {

    private String deviceId;

    @DynamoDbPartitionKey
    public String getDeviceId() {
        return deviceId;
    }

    public void setDeviceId(String deviceId) {
        this.deviceId = deviceId;
    }
}
