package com.anpr.devicemanagement.storage;

import com.anpr.devicemanagement.config.AwsProperties;
import com.anpr.devicemanagement.internal.models.ModelName;
import com.anpr.devicemanagement.internal.models.ModelRelease;
import com.anpr.devicemanagement.shared.error.TechnicalException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import software.amazon.awssdk.core.ResponseBytes;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.GetObjectRequest;
import software.amazon.awssdk.services.s3.model.GetObjectResponse;
import software.amazon.awssdk.services.s3.model.NoSuchKeyException;
import tools.jackson.databind.json.JsonMapper;

import java.nio.charset.StandardCharsets;
import java.util.function.Consumer;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class S3ModelReleasesTest {
    private static final String SHA = "0123456789abcdef".repeat(4);

    @Mock
    private S3Client s3;

    private S3ModelReleases releases;

    @BeforeEach
    void setUp() {
        AwsProperties aws = new AwsProperties("eu-central-1", null, new AwsProperties.S3("images", "models-bucket"), null, null);
        releases = new S3ModelReleases(s3, aws, JsonMapper.builder().build());
    }

    @Test
    void readsTheReleaseDescriptionOfTheVersion() {
        stored("""
                {"model": "ocr", "version": "v3", "publishedAt": "2026-11-12T10:00:00Z",
                 "files": [{"name": "model.onnx", "sha256": "%s", "sizeBytes": 2048},
                           {"name": "plate_config.yaml", "sha256": "%s", "sizeBytes": 300}]}
                """.formatted(SHA, SHA));

        ModelRelease release = releases.find(ModelName.OCR, "v3").orElseThrow();

        assertThat(release.files()).extracting(ModelRelease.File::name).containsExactly("model.onnx", "plate_config.yaml");
        assertThat(release.files().getFirst().sizeBytes()).isEqualTo(2048);
        assertThat(requestedKey()).isEqualTo("models/ocr/v3/release.json");
    }

    @Test
    void aMissingDescriptionMeansNotPublished() {
        when(s3.getObjectAsBytes(any(Consumer.class))).thenThrow(NoSuchKeyException.builder().build());

        assertThat(releases.find(ModelName.DETECTOR, "v9")).isEmpty();
    }

    @Test
    void aDescriptionOfAnotherVersionOrWithAnUnsafeFileNameIsRefused() {
        stored("""
                {"model": "ocr", "version": "v2", "files": [{"name": "model.onnx", "sha256": "%s", "sizeBytes": 1}]}
                """.formatted(SHA));
        assertThatThrownBy(() -> releases.find(ModelName.OCR, "v3")).isInstanceOf(TechnicalException.class);

        stored("""
                {"model": "ocr", "version": "v3", "files": [{"name": "../x", "sha256": "%s", "sizeBytes": 1}]}
                """.formatted(SHA));
        assertThatThrownBy(() -> releases.find(ModelName.OCR, "v3")).isInstanceOf(TechnicalException.class);

        stored("not json");
        assertThatThrownBy(() -> releases.find(ModelName.OCR, "v3")).isInstanceOf(TechnicalException.class);
    }

    @SuppressWarnings("unchecked")
    private void stored(String json) {
        when(s3.getObjectAsBytes(any(Consumer.class))).thenReturn(
                ResponseBytes.fromByteArray(GetObjectResponse.builder().build(), json.getBytes(StandardCharsets.UTF_8)));
    }

    @SuppressWarnings("unchecked")
    private String requestedKey() {
        ArgumentCaptor<Consumer<GetObjectRequest.Builder>> captor = ArgumentCaptor.forClass(Consumer.class);
        verify(s3).getObjectAsBytes(captor.capture());
        GetObjectRequest.Builder builder = GetObjectRequest.builder();
        captor.getValue().accept(builder);
        assertThat(builder.build().bucket()).isEqualTo("models-bucket");
        return builder.build().key();
    }
}
