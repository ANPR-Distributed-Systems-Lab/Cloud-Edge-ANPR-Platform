package com.anpr.devicemanagement.internal.devices;

import lombok.Getter;
import lombok.Setter;
import software.amazon.awssdk.enhanced.dynamodb.mapper.annotations.DynamoDbBean;
import software.amazon.awssdk.enhanced.dynamodb.mapper.annotations.DynamoDbPartitionKey;
import software.amazon.awssdk.enhanced.dynamodb.mapper.annotations.DynamoDbSecondaryPartitionKey;

import java.time.Instant;
import java.util.UUID;

/**
 * A registered device and the account that owns it (table devices, the source of truth of the ownership).
 * <p>
 * The keys must match the table Terraform creates: partition key {@code deviceId} (string) and the index
 * {@value #ACCOUNT_INDEX} by {@code accountId}. Setters exist for the DynamoDB mapper only; new devices are created
 * with {@link #register}.
 */
@DynamoDbBean
@Getter
@Setter
public class Device {
    public static final String ACCOUNT_INDEX = "accountId-index";

    /** The first version of the ownership, carried by the device.paired event of a new device. */
    static final long FIRST_VERSION = 1;

    /** Cognito sub of the device account. */
    private UUID deviceId;

    /** The owning user account (Cognito sub of the person). */
    private UUID accountId;

    /** Login of the device in Cognito, needed to delete its user. */
    private String username;

    private Instant createdAt;

    /** Version of the ownership: raised on every change and sent in the device events, so consumers drop stale ones. */
    private Long version;

    public static Device register(UUID deviceId, UUID accountId, String username, Instant now) {
        Device device = new Device();
        device.deviceId = deviceId;
        device.accountId = accountId;
        device.username = username;
        device.createdAt = now;
        device.version = FIRST_VERSION;
        return device;
    }

    /** Version of the device.unpaired event that ends the ownership. */
    public long unpairedVersion() {
        return version + 1;
    }

    @DynamoDbPartitionKey
    public UUID getDeviceId() {
        return deviceId;
    }

    @DynamoDbSecondaryPartitionKey(indexNames = ACCOUNT_INDEX)
    public UUID getAccountId() {
        return accountId;
    }
}
