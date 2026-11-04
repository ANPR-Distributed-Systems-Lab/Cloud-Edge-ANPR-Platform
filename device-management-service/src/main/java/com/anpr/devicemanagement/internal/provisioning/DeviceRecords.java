package com.anpr.devicemanagement.internal.provisioning;

import com.anpr.devicemanagement.internal.configuration.DeviceConfiguration;
import com.anpr.devicemanagement.internal.devices.Device;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Repository;
import software.amazon.awssdk.enhanced.dynamodb.DynamoDbEnhancedClient;
import software.amazon.awssdk.enhanced.dynamodb.DynamoDbTable;
import software.amazon.awssdk.enhanced.dynamodb.Expression;
import software.amazon.awssdk.enhanced.dynamodb.Key;
import software.amazon.awssdk.enhanced.dynamodb.model.TransactPutItemEnhancedRequest;

import java.util.UUID;

/**
 * The registration of a device and its configuration, written and deleted together in one DynamoDB transaction, so a
 * device never exists without its configuration.
 */
@Repository
@RequiredArgsConstructor
public class DeviceRecords {
    private final DynamoDbEnhancedClient client;
    private final DynamoDbTable<Device> devices;
    private final DynamoDbTable<DeviceConfiguration> configurations;

    /** Fails if the device is already registered (the configuration is protected by its version, still unset). */
    public void insert(Device device, DeviceConfiguration configuration) {
        Expression deviceIsNew = Expression.builder().expression("attribute_not_exists(deviceId)").build();
        client.transactWriteItems(transaction -> transaction
                .addPutItem(devices, TransactPutItemEnhancedRequest.builder(Device.class)
                        .item(device)
                        .conditionExpression(deviceIsNew)
                        .build())
                .addPutItem(configurations, configuration));
    }

    /** Idempotent: deleting a device that is not registered (any more) succeeds. */
    public void remove(UUID deviceId) {
        Key key = Key.builder().partitionValue(deviceId.toString()).build();
        client.transactWriteItems(transaction -> transaction
                .addDeleteItem(devices, key)
                .addDeleteItem(configurations, key));
    }
}
