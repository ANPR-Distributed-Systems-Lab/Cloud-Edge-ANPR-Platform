package com.anpr.devicemanagement.local;

import com.anpr.devicemanagement.config.AwsProperties;
import com.anpr.devicemanagement.internal.configuration.DeviceConfiguration;
import com.anpr.devicemanagement.internal.devices.Device;
import com.anpr.devicemanagement.internal.metrics.Measurement;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.enhanced.dynamodb.DynamoDbTable;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.dynamodb.DynamoDbClient;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;

/**
 * Wiring of the local profile. The profile replaces the account directory with one that accepts everybody, so it
 * refuses to start unless DynamoDB is local: in AWS the endpoint is never set.
 */
@Configuration
@Profile("local")
public class LocalConfig {

    public LocalConfig(AwsProperties aws) {
        if (!aws.dynamodb().usesLocalEndpoint()) {
            throw new IllegalStateException("The local profile needs app.aws.dynamodb.endpoint (DynamoDB Local)");
        }
    }

    @Bean
    ApplicationRunner createLocalTables(DynamoDbClient client, DynamoDbTable<Device> devices,
                                        DynamoDbTable<DeviceConfiguration> configurations,
                                        DynamoDbTable<Measurement> metrics) {
        return arguments -> LocalTables.createMissing(client, devices, configurations, metrics);
    }

    /** There is no local S3: the URLs are well-formed but signed with dummy credentials and lead nowhere. */
    @Bean
    S3Presigner s3Presigner(AwsProperties aws) {
        return S3Presigner.builder()
                .region(Region.of(aws.region()))
                .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("local", "local")))
                .build();
    }
}
