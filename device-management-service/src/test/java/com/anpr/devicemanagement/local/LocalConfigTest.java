package com.anpr.devicemanagement.local;

import com.anpr.devicemanagement.config.AwsProperties;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class LocalConfigTest {

    @Test
    void refusesToStartWithoutALocalDynamoDb() {
        assertThatThrownBy(() -> new LocalConfig(awsWithEndpoint("")))
                .isInstanceOf(IllegalStateException.class);
    }

    @Test
    void startsWithDynamoDbLocal() {
        assertThatCode(() -> new LocalConfig(awsWithEndpoint("http://localhost:8000"))).doesNotThrowAnyException();
    }

    private static AwsProperties awsWithEndpoint(String endpoint) {
        return new AwsProperties("eu-central-1", new AwsProperties.DynamoDb(endpoint, null), null, null, null);
    }
}
