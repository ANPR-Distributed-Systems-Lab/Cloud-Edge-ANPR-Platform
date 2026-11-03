package com.anpr.devicemanagement.support;

import com.anpr.devicemanagement.internal.configuration.DeviceConfiguration;
import com.anpr.devicemanagement.internal.devices.Device;
import com.anpr.devicemanagement.internal.metrics.Measurement;
import com.anpr.devicemanagement.local.LocalTables;
import org.junit.jupiter.api.BeforeEach;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.utility.DockerImageName;
import software.amazon.awssdk.enhanced.dynamodb.DynamoDbTable;
import software.amazon.awssdk.services.dynamodb.DynamoDbClient;

/**
 * Base of the integration tests that need DynamoDB: one DynamoDB Local container for the whole test run (stopped by
 * Testcontainers at the end) and the tables created from the item classes the way Terraform creates them, including
 * the index of the registry (the same code as the local profile). Test data is isolated by random ids, so tests
 * never clean up.
 */
@SpringBootTest
@ActiveProfiles("test")
public abstract class DynamoDbLocalSupport {
    private static final int PORT = 8000;

    private static final GenericContainer<?> DYNAMODB = new GenericContainer<>(DockerImageName.parse("amazon/dynamodb-local:3.3.2"))
            .withCommand("-jar", "DynamoDBLocal.jar", "-inMemory", "-sharedDb")
            .withExposedPorts(PORT);

    static {
        DYNAMODB.start();
    }

    @DynamicPropertySource
    static void dynamoDbLocal(DynamicPropertyRegistry registry) {
        registry.add("app.aws.dynamodb.endpoint", () -> "http://" + DYNAMODB.getHost() + ":" + DYNAMODB.getMappedPort(PORT));
    }

    @Autowired
    protected DynamoDbClient dynamoDbClient;
    @Autowired
    protected DynamoDbTable<Device> devicesTable;
    @Autowired
    protected DynamoDbTable<DeviceConfiguration> configurationsTable;
    @Autowired
    protected DynamoDbTable<Measurement> measurementsTable;

    @BeforeEach
    void createTablesOnce() {
        LocalTables.createMissing(dynamoDbClient, devicesTable, configurationsTable, measurementsTable);
    }
}
