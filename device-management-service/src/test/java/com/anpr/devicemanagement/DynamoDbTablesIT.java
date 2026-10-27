package com.anpr.devicemanagement;

import com.anpr.devicemanagement.internal.configuration.DeviceConfiguration;
import com.anpr.devicemanagement.internal.status.DeviceStatus;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;
import software.amazon.awssdk.enhanced.dynamodb.DynamoDbTable;
import software.amazon.awssdk.enhanced.dynamodb.Key;
import software.amazon.awssdk.enhanced.dynamodb.model.QueryConditional;
import software.amazon.awssdk.services.dynamodb.DynamoDbClient;
import software.amazon.awssdk.services.dynamodb.model.AttributeDefinition;
import software.amazon.awssdk.services.dynamodb.model.KeySchemaElement;
import software.amazon.awssdk.services.dynamodb.model.KeyType;
import software.amazon.awssdk.services.dynamodb.model.ScalarAttributeType;
import software.amazon.awssdk.services.dynamodb.model.TableDescription;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * The application's DynamoDB wiring against DynamoDB Local: endpoint, credentials and the
 * item classes. The tables are created here from the item classes, and the assertions pin the
 * key schemas that Terraform creates in AWS (infrastructure/envs/dev/device-management-service.tf):
 * if an item class and the Terraform table drift apart, this test fails.
 */
@SpringBootTest
@Testcontainers
class DynamoDbTablesIT {

    private static final int DYNAMODB_PORT = 8000;
    private static final String CONFIGURATIONS = "device-configurations";
    private static final String STATUSES = "device-statuses";

    @Container
    static final GenericContainer<?> DYNAMODB = new GenericContainer<>(DockerImageName.parse("amazon/dynamodb-local:3.3.2"))
            .withCommand("-jar", "DynamoDBLocal.jar", "-inMemory", "-sharedDb")
            .withExposedPorts(DYNAMODB_PORT);

    @DynamicPropertySource
    static void dynamoDbLocal(DynamicPropertyRegistry registry) {
        registry.add("app.aws.dynamodb.endpoint",
                () -> "http://" + DYNAMODB.getHost() + ":" + DYNAMODB.getMappedPort(DYNAMODB_PORT));
        registry.add("app.aws.dynamodb.tables.device-configurations", () -> CONFIGURATIONS);
        registry.add("app.aws.dynamodb.tables.device-statuses", () -> STATUSES);
    }

    @Autowired
    private DynamoDbClient client;

    @Autowired
    private DynamoDbTable<DeviceConfiguration> configurations;

    @Autowired
    private DynamoDbTable<DeviceStatus> statuses;

    /** The container lives for the whole class, so the tables are created by the first test only. */
    @BeforeEach
    void createTablesOnce() {
        if (!client.listTables().tableNames().contains(CONFIGURATIONS)) {
            configurations.createTable();
            statuses.createTable();
        }
    }

    @Test
    void deviceConfigurationsAreKeyedByDeviceId() {
        TableDescription table = describe(CONFIGURATIONS);

        assertThat(table.keySchema()).containsExactly(key("deviceId", KeyType.HASH));
        assertThat(table.attributeDefinitions()).containsExactly(attribute("deviceId", ScalarAttributeType.S));
    }

    @Test
    void deviceStatusesAreKeyedByDeviceIdAndNumericReportedAt() {
        TableDescription table = describe(STATUSES);

        assertThat(table.keySchema()).containsExactlyInAnyOrder(
                key("deviceId", KeyType.HASH),
                key("reportedAt", KeyType.RANGE));
        assertThat(table.attributeDefinitions()).containsExactlyInAnyOrder(
                attribute("deviceId", ScalarAttributeType.S),
                attribute("reportedAt", ScalarAttributeType.N));
    }

    @Test
    void theTablesAreReachableThroughTheTypedBeans() {
        Key unknownDevice = Key.builder().partitionValue("unknown-device").build();

        assertThat(configurations.getItem(unknownDevice)).isNull();
        assertThat(statuses.query(QueryConditional.keyEqualTo(unknownDevice)).items()).isEmpty();
    }

    private TableDescription describe(String tableName) {
        return client.describeTable(request -> request.tableName(tableName)).table();
    }

    private static KeySchemaElement key(String name, KeyType type) {
        return KeySchemaElement.builder().attributeName(name).keyType(type).build();
    }

    private static AttributeDefinition attribute(String name, ScalarAttributeType type) {
        return AttributeDefinition.builder().attributeName(name).attributeType(type).build();
    }
}
