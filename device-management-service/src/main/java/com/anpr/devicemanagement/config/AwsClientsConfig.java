package com.anpr.devicemanagement.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.cognitoidentityprovider.CognitoIdentityProviderClient;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;
import software.amazon.awssdk.services.sns.SnsClient;

/**
 * Clients of the other AWS services. Credentials come from the SDK's default chain (the ECS task role in AWS);
 * building a client does not call AWS, so the application starts without credentials.
 */
@Configuration
public class AwsClientsConfig {

    @Bean
    CognitoIdentityProviderClient cognitoClient(AwsProperties aws) {
        return CognitoIdentityProviderClient.builder().region(Region.of(aws.region())).build();
    }

    @Bean
    SnsClient snsClient(AwsProperties aws) {
        return SnsClient.builder().region(Region.of(aws.region())).build();
    }

    /** Reads the release descriptions of the models (internal/models); there is no S3 in the local profile. */
    @Bean
    @Profile("!local")
    S3Client s3Client(AwsProperties aws) {
        return S3Client.builder().region(Region.of(aws.region())).build();
    }

    /** Signing is local: no request is sent to S3 until the device uploads or downloads with the URL. */
    @Bean
    @Profile("!local")
    S3Presigner s3Presigner(AwsProperties aws) {
        return S3Presigner.builder().region(Region.of(aws.region())).build();
    }
}
