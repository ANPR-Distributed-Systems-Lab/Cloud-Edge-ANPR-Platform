package com.anpr.devicemanagement;

import com.anpr.devicemanagement.internal.configuration.DeviceConfiguration;
import com.anpr.devicemanagement.internal.devices.Device;
import com.anpr.devicemanagement.internal.metrics.Measurement;
import com.anpr.devicemanagement.support.DynamoDbLocalSupport;
import com.anpr.devicemanagement.support.TestData;
import org.junit.jupiter.api.Test;
import software.amazon.awssdk.enhanced.dynamodb.model.QueryConditional;
import software.amazon.awssdk.services.dynamodb.model.AttributeDefinition;
import software.amazon.awssdk.services.dynamodb.model.AttributeValue;
import software.amazon.awssdk.services.dynamodb.model.KeySchemaElement;
import software.amazon.awssdk.services.dynamodb.model.KeyType;
import software.amazon.awssdk.services.dynamodb.model.ScalarAttributeType;
import software.amazon.awssdk.services.dynamodb.model.TableDescription;

import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * The item classes against DynamoDB Local. The tables are created from the item classes, and the assertions pin the
 * key schemas Terraform creates in AWS (infrastructure/envs/dev/device-management-service.tf): if an item class and
 * the Terraform table drift apart, this test fails. The raw items pin the stored attribute names and types.
 */
class DynamoDbTablesIT extends DynamoDbLocalSupport {

    @Test
    void devicesAreKeyedByDeviceIdAndIndexedByAccountId() {
        TableDescription table = describe(devicesTable.tableName());

        assertThat(table.keySchema()).containsExactly(key("deviceId", KeyType.HASH));
        assertThat(table.attributeDefinitions()).containsExactlyInAnyOrder(
                attribute("deviceId", ScalarAttributeType.S),
                attribute("accountId", ScalarAttributeType.S));
        assertThat(table.globalSecondaryIndexes()).singleElement().satisfies(index -> {
            assertThat(index.indexName()).isEqualTo("accountId-index");
            assertThat(index.keySchema()).containsExactly(key("accountId", KeyType.HASH));
        });
    }

    @Test
    void deviceConfigurationsAreKeyedByDeviceId() {
        TableDescription table = describe(configurationsTable.tableName());

        assertThat(table.keySchema()).containsExactly(key("deviceId", KeyType.HASH));
        assertThat(table.attributeDefinitions()).containsExactly(attribute("deviceId", ScalarAttributeType.S));
    }

    @Test
    void deviceMetricsAreKeyedByDeviceIdAndNumericRecordedAt() {
        TableDescription table = describe(measurementsTable.tableName());

        assertThat(table.keySchema()).containsExactlyInAnyOrder(
                key("deviceId", KeyType.HASH),
                key("recordedAt", KeyType.RANGE));
        assertThat(table.attributeDefinitions()).containsExactlyInAnyOrder(
                attribute("deviceId", ScalarAttributeType.S),
                attribute("recordedAt", ScalarAttributeType.N));
    }

    @Test
    void aMeasurementStoresItsMomentInMillisAndItsExpiryInSeconds() {
        UUID deviceId = UUID.randomUUID();
        Instant recordedAt = Instant.parse("2026-11-02T10:00:00.123Z");
        Measurement measurement = TestData.measurement(recordedAt);
        measurement.storeFor(deviceId, Duration.ofDays(7));
        measurementsTable.putItem(measurement);

        Map<String, AttributeValue> item = rawItem(measurementsTable.tableName(), Map.of(
                "deviceId", AttributeValue.fromS(deviceId.toString()),
                "recordedAt", AttributeValue.fromN(String.valueOf(recordedAt.toEpochMilli()))));

        assertThat(item.get("expiresAt").n()).isEqualTo(String.valueOf(recordedAt.plus(Duration.ofDays(7)).getEpochSecond()));
        assertThat(item.get("gps").m().get("fix").s()).isEqualTo("FIX_3D");
    }

    @Test
    void aConfigurationStoresItsSettingsAsTopLevelAttributes() {
        UUID deviceId = UUID.randomUUID();
        configurationsTable.putItem(DeviceConfiguration.initial(deviceId, TestData.settings(60), Instant.EPOCH));

        Map<String, AttributeValue> item = rawItem(configurationsTable.tableName(),
                Map.of("deviceId", AttributeValue.fromS(deviceId.toString())));

        assertThat(item).containsKeys("version", "updatedAt", "plateCooldownSeconds", "batching", "ml", "models", "intervals",
                "camera");
        assertThat(item.get("camera").m().get("exposure").m().get("mode").s()).isEqualTo("MANUAL");
    }

    @Test
    void aDeviceIsFoundThroughTheIndexOfItsAccount() {
        Device device = Device.register(UUID.randomUUID(), UUID.randomUUID(), "rpi-index", Instant.EPOCH);
        devicesTable.putItem(device);

        assertThat(devicesTable.index(Device.ACCOUNT_INDEX)
                .query(request -> request.queryConditional(
                        QueryConditional.keyEqualTo(key -> key.partitionValue(device.getAccountId().toString()))))
                .stream().flatMap(page -> page.items().stream()))
                .singleElement()
                .satisfies(found -> assertThat(found.getDeviceId()).isEqualTo(device.getDeviceId()));
    }

    private Map<String, AttributeValue> rawItem(String table, Map<String, AttributeValue> key) {
        return dynamoDbClient.getItem(request -> request.tableName(table).key(key)).item();
    }

    private TableDescription describe(String tableName) {
        return dynamoDbClient.describeTable(request -> request.tableName(tableName)).table();
    }

    private static KeySchemaElement key(String name, KeyType type) {
        return KeySchemaElement.builder().attributeName(name).keyType(type).build();
    }

    private static AttributeDefinition attribute(String name, ScalarAttributeType type) {
        return AttributeDefinition.builder().attributeName(name).attributeType(type).build();
    }
}
