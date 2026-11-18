package com.anpr.operations.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;
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

    /** Signing is local: no request is sent to S3 until the browser opens the URL. */
    @Bean
    @Profile("!local & !test")
    S3Presigner s3Presigner(AwsProperties aws) {
        return S3Presigner.builder()
                .region(Region.of(aws.region()))
                .build();
    }

    /** No AWS account locally or in tests: the URLs are well-formed but signed with dummy keys and lead nowhere. */
    @Bean
    @Profile("local | test")
    S3Presigner offlineS3Presigner(AwsProperties aws) {
        return S3Presigner.builder()
                .region(Region.of(aws.region()))
                .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("local", "local")))
                .build();
    }
}