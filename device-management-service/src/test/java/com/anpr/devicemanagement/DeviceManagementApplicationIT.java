package com.anpr.devicemanagement;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

/**
 * The application starts with the configuration it gets in AWS: resource names set, no local DynamoDB endpoint.
 * Building the AWS clients does not call AWS, so no credentials are needed.
 */
@SpringBootTest
@ActiveProfiles("test")
class DeviceManagementApplicationIT {

    @Test
    void contextLoads() {
    }
}
