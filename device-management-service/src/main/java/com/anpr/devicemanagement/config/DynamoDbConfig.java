package com.anpr.devicemanagement.config;

import com.anpr.devicemanagement.internal.configuration.DeviceConfiguration;
import com.anpr.devicemanagement.internal.status.DeviceStatus;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.enhanced.dynamodb.DynamoDbEnhancedClient;
import software.amazon.awssdk.enhanced.dynamodb.DynamoDbTable;
import software.amazon.awssdk.enhanced.dynamodb.TableSchema;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.dynamodb.DynamoDbClient;
import software.amazon.awssdk.services.dynamodb.DynamoDbClientBuilder;

import java.net.URI;

/**
 * DynamoDB access: one client for the whole application and one typed table per item class.
 * Repositories inject the {@link DynamoDbTable} beans and never deal with table names or clients.
 */
@Configuration
@EnableConfigurationProperties(AwsProperties.class)
public class DynamoDbConfig {

    private static final Logger log = LoggerFactory.getLogger(DynamoDbConfig.class);

    @Bean
    DynamoDbClient dynamoDbClient(AwsProperties aws) {
        DynamoDbClientBuilder builder = DynamoDbClient.builder().region(Region.of(aws.region()));

        if (aws.dynamodb().usesLocalEndpoint()) {
            // DynamoDB Local accepts any credentials, so fixed dummy ones avoid looking up real ones.
            log.info("Using the local DynamoDB endpoint {}", aws.dynamodb().endpoint());
            builder.endpointOverride(URI.create(aws.dynamodb().endpoint()))
                    .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("local", "local")));
        }
        // Otherwise the SDK's default credentials chain finds the ECS task role (or a local AWS profile).

        return builder.build();
    }

    @Bean
    DynamoDbEnhancedClient dynamoDbEnhancedClient(DynamoDbClient dynamoDbClient) {
        return DynamoDbEnhancedClient.builder().dynamoDbClient(dynamoDbClient).build();
    }

    @Bean
    DynamoDbTable<DeviceConfiguration> deviceConfigurationsTable(DynamoDbEnhancedClient client, AwsProperties aws) {
        return client.table(aws.dynamodb().tables().deviceConfigurations(), TableSchema.fromBean(DeviceConfiguration.class));
    }

    @Bean
    DynamoDbTable<DeviceStatus> deviceStatusesTable(DynamoDbEnhancedClient client, AwsProperties aws) {
        return client.table(aws.dynamodb().tables().deviceStatuses(), TableSchema.fromBean(DeviceStatus.class));
    }
}
