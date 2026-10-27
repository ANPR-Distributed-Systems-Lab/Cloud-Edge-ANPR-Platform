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
 */
@Validated
@ConfigurationProperties(prefix = "app.aws")
public record AwsProperties(@NotBlank String region, @Valid @NotNull DynamoDb dynamodb) {

    /**
     * @param endpoint only for DynamoDB Local (development and tests), e.g. http://localhost:8000; empty in AWS
     * @param tables   names of the tables Terraform creates
     */
    public record DynamoDb(String endpoint, @Valid @NotNull Tables tables) {

        public boolean usesLocalEndpoint() {
            return StringUtils.hasText(endpoint);
        }
    }

    public record Tables(@NotBlank String deviceConfigurations, @NotBlank String deviceStatuses) {
    }
}
