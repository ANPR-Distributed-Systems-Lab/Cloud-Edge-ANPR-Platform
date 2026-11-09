package com.anpr.operations.shared.storage;

import com.anpr.operations.config.AwsProperties;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;

import java.net.URI;
import java.time.Duration;

import static org.assertj.core.api.Assertions.assertThat;

class ImageUrlSignerTest {
    private final S3Presigner presigner = S3Presigner.builder()
            .region(Region.EU_CENTRAL_1)
            .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("key", "secret")))
            .build();

    private final ImageUrlSigner signer = new ImageUrlSigner(presigner, new AwsProperties("eu-central-1",
            new AwsProperties.Sqs("device-events", "events"),
            new AwsProperties.S3("anpr-images", Duration.ofMinutes(15))));

    @AfterEach
    void closePresigner() {
        presigner.close();
    }

    @Test
    void urlPointsToThePhotoInTheImagesBucket() {
        URI url = signer.urlOf("images/5e1c0000-0000-4000-8000-000000000002/2026/10/30/frame.jpg");

        assertThat(url.getHost()).isEqualTo("anpr-images.s3.eu-central-1.amazonaws.com");
        assertThat(url.getPath()).isEqualTo("/images/5e1c0000-0000-4000-8000-000000000002/2026/10/30/frame.jpg");
    }

    @Test
    void urlIsSignedAndExpiresAfterTheConfiguredTime() {
        URI url = signer.urlOf("images/x.jpg");

        assertThat(url.getQuery())
                .contains("X-Amz-Expires=900")
                .contains("X-Amz-Signature=");
    }
}