package com.anpr.devicemanagement.internal.devices;

import org.springframework.stereotype.Repository;
import software.amazon.awssdk.enhanced.dynamodb.DynamoDbIndex;
import software.amazon.awssdk.enhanced.dynamodb.DynamoDbTable;
import software.amazon.awssdk.enhanced.dynamodb.Key;
import software.amazon.awssdk.enhanced.dynamodb.model.GetItemEnhancedRequest;
import software.amazon.awssdk.enhanced.dynamodb.model.QueryConditional;

import java.util.Optional;
import java.util.UUID;

/** Reads of the device registry. Devices are written by the provisioning, together with their configuration. */
@Repository
public class DeviceRepository {
    private final DynamoDbTable<Device> table;
    private final DynamoDbIndex<Device> byAccount;

    public DeviceRepository(DynamoDbTable<Device> devicesTable) {
        this.table = devicesTable;
        this.byAccount = devicesTable.index(Device.ACCOUNT_INDEX);
    }

    /** Strongly consistent: a device deleted a moment ago is not found any more. */
    public Optional<Device> findById(UUID deviceId) {
        GetItemEnhancedRequest request = GetItemEnhancedRequest.builder()
                .key(key(deviceId))
                .consistentRead(true)
                .build();
        return Optional.ofNullable(table.getItem(request));
    }

    /**
     * The device of an account (one per account for now). Index reads are eventually consistent, so a device
     * created or deleted within the last second may be missed.
     */
    public Optional<Device> findByAccountId(UUID accountId) {
        return byAccount.query(QueryConditional.keyEqualTo(key(accountId))).stream()
                .flatMap(page -> page.items().stream())
                .findFirst();
    }

    private static Key key(UUID id) {
        return Key.builder().partitionValue(id.toString()).build();
    }
}
