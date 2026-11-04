package com.anpr.devicemanagement.local;

import com.anpr.devicemanagement.internal.configuration.DeviceConfiguration;
import com.anpr.devicemanagement.internal.devices.Device;
import com.anpr.devicemanagement.internal.metrics.Measurement;
import lombok.AccessLevel;
import lombok.NoArgsConstructor;
import software.amazon.awssdk.enhanced.dynamodb.DynamoDbTable;
import software.amazon.awssdk.enhanced.dynamodb.model.CreateTableEnhancedRequest;
import software.amazon.awssdk.enhanced.dynamodb.model.EnhancedGlobalSecondaryIndex;
import software.amazon.awssdk.services.dynamodb.DynamoDbClient;
import software.amazon.awssdk.services.dynamodb.model.ProjectionType;

import java.util.List;

/**
 * Creates the tables in DynamoDB Local from the item classes, with the same keys and index as Terraform creates in
 * AWS. Used by the local profile and by the integration tests.
 */
@NoArgsConstructor(access = AccessLevel.PRIVATE)
public final class LocalTables {

    public static void createMissing(DynamoDbClient client, DynamoDbTable<Device> devices,
                                     DynamoDbTable<DeviceConfiguration> configurations,
                                     DynamoDbTable<Measurement> metrics) {
        List<String> existing = client.listTables().tableNames();
        if (!existing.contains(devices.tableName())) {
            devices.createTable(CreateTableEnhancedRequest.builder()
                    .globalSecondaryIndices(EnhancedGlobalSecondaryIndex.builder()
                            .indexName(Device.ACCOUNT_INDEX)
                            .projection(projection -> projection.projectionType(ProjectionType.ALL))
                            .build())
                    .build());
        }
        if (!existing.contains(configurations.tableName())) {
            configurations.createTable();
        }
        if (!existing.contains(metrics.tableName())) {
            metrics.createTable();
        }
    }
}
