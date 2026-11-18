package com.anpr.operations.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.sqs.SqsClient;

/**
 * AWS SDK clients. Credentials come from the default provider chain: the ECS task role in AWS,
 * the developer's profile or environment variables elsewhere. No keys in configuration files.
 */
@Configuration
public class AwsClientsConfig {

    @Bean
    SqsClient sqsClient(AwsProperties aws) {
        return SqsClient.builder()
                .region(Region.of(aws.region()))
                .build();
    }
}
