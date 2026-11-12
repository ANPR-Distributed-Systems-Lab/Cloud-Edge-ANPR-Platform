package com.anpr.devicemanagement.config;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.util.StringUtils;
import org.springframework.validation.annotation.Validated;

/**
 * AWS settings of the service, bound from {@code app.aws.*} (see application.yaml).
 * A missing required value fails the startup instead of the first request.
 *
 * @param region   AWS region of the clients
 * @param dynamodb DynamoDB endpoint and table names
 * @param s3       buckets of the photos the devices upload and of the models they download
 * @param cognito  user pool of people and devices
 * @param sns      topic of the device events
 */
@Validated
@ConfigurationProperties(prefix = "app.aws")
public record AwsProperties(
        @NotBlank String region,
        @Valid @NotNull DynamoDb dynamodb,
        @Valid @NotNull S3 s3,
        @Valid @NotNull Cognito cognito,
        @Valid @NotNull Sns sns) {

    /**
     * @param endpoint only for DynamoDB Local (development and tests), e.g. http://localhost:8000; empty in AWS
     * @param tables   names of the tables Terraform creates
     */
    public record DynamoDb(String endpoint, @Valid @NotNull Tables tables) {

        public boolean usesLocalEndpoint() {
            return StringUtils.hasText(endpoint);
        }
    }

    public record Tables(@NotBlank String devices, @NotBlank String deviceConfigurations, @NotBlank String deviceMetrics) {
    }

    public record S3(@NotBlank String imagesBucket, @NotBlank String modelsBucket) {
    }

    /**
     * @param usersGroup   group of people; only they may own a device
     * @param devicesGroup group the users of new devices are put in
     */
    public record Cognito(@NotBlank String userPoolId, @NotBlank String usersGroup, @NotBlank String devicesGroup) {
    }

    public record Sns(@NotBlank String deviceEventsTopicArn) {
    }
}
