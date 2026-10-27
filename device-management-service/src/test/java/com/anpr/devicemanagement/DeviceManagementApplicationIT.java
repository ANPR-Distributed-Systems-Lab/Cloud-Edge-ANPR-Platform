package com.anpr.devicemanagement;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;

/**
 * The application starts with the configuration it gets in AWS: table names set, no local
 * DynamoDB endpoint. Building the AWS clients does not call AWS, so no credentials are needed.
 */
@SpringBootTest(properties = {
        "app.aws.dynamodb.tables.device-configurations=device-configurations",
        "app.aws.dynamodb.tables.device-statuses=device-statuses",
})
class DeviceManagementApplicationIT {

    @Test
    void contextLoads() {
    }
}
