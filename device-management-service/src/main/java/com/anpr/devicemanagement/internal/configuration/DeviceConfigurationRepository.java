package com.anpr.devicemanagement.internal.configuration;

import com.anpr.devicemanagement.shared.error.ConflictException;
import com.anpr.devicemanagement.shared.error.ErrorCodes;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Repository;
import software.amazon.awssdk.enhanced.dynamodb.DynamoDbTable;
import software.amazon.awssdk.enhanced.dynamodb.Key;
import software.amazon.awssdk.enhanced.dynamodb.model.GetItemEnhancedRequest;
import software.amazon.awssdk.services.dynamodb.model.ConditionalCheckFailedException;

import java.util.Optional;
import java.util.UUID;

/** Configurations are created by the provisioning, together with their device; this repository reads and edits them. */
@Repository
@RequiredArgsConstructor
public class DeviceConfigurationRepository {
    private final DynamoDbTable<DeviceConfiguration> table;

    public Optional<DeviceConfiguration> findByDeviceId(UUID deviceId) {
        GetItemEnhancedRequest request = GetItemEnhancedRequest.builder()
                .key(Key.builder().partitionValue(deviceId.toString()).build())
                .consistentRead(true)
                .build();
        return Optional.ofNullable(table.getItem(request));
    }

    /**
     * Writes the configuration if the stored version is still the one it was read with, and raises the version.
     *
     * @throws ConflictException CONCURRENT_MODIFICATION when someone else saved it in between
     */
    public DeviceConfiguration update(DeviceConfiguration configuration) {
        try {
            return table.updateItem(configuration);
        } catch (ConditionalCheckFailedException e) {
            throw new ConflictException(ErrorCodes.CONCURRENT_MODIFICATION, "Configuration was modified by someone else");
        }
    }
}
