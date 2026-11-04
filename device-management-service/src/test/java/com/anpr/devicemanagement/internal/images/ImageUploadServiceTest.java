package com.anpr.devicemanagement.internal.images;

import com.anpr.devicemanagement.config.AwsProperties;
import com.anpr.devicemanagement.internal.devices.Device;
import com.anpr.devicemanagement.internal.devices.DeviceLookup;
import com.anpr.devicemanagement.shared.error.ErrorCodes;
import com.anpr.devicemanagement.shared.error.FieldViolation;
import com.anpr.devicemanagement.shared.error.ForbiddenException;
import com.anpr.devicemanagement.shared.error.ValidationException;
import com.anpr.devicemanagement.shared.security.Caller;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import software.amazon.awssdk.auth.credentials.AwsBasicCredentials;
import software.amazon.awssdk.auth.credentials.StaticCredentialsProvider;
import software.amazon.awssdk.regions.Region;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.InstanceOfAssertFactories.list;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/** Uses a real presigner: signing is a local computation, no request reaches S3. */
@ExtendWith(MockitoExtension.class)
class ImageUploadServiceTest {

    private static final UUID DEVICE_ID = UUID.fromString("7d3f2c1e-0000-4000-8000-000000000000");
    private static final UUID FRAME_ID = UUID.fromString("0192f3a4-7c1e-7000-b5c3-1d2e3f4a5b6c");
    private static final Instant NOW = Instant.parse("2026-11-02T10:00:00Z");
    private static final Caller DEVICE = new Caller.DeviceCaller(DEVICE_ID);

    @Mock
    private DeviceLookup deviceLookup;

    private S3Presigner presigner;
    private ImageUploadService service;

    @BeforeEach
    void setUp() {
        presigner = S3Presigner.builder()
                .region(Region.EU_CENTRAL_1)
                .credentialsProvider(StaticCredentialsProvider.create(AwsBasicCredentials.create("test", "test")))
                .build();
        AwsProperties aws = new AwsProperties("eu-central-1", null, new AwsProperties.S3("images-bucket"), null, null);
        ImagesProperties properties = new ImagesProperties(Duration.ofMinutes(30), Duration.ofDays(30), Duration.ofMinutes(5));
        service = new ImageUploadService(deviceLookup, presigner, aws, properties, Clock.fixed(NOW, ZoneOffset.UTC));
    }

    @AfterEach
    void tearDown() {
        presigner.close();
    }

    @Test
    void theKeyIsUnderTheDeviceAndTheUtcDateOfCapture() {
        when(deviceLookup.deviceOf(DEVICE)).thenReturn(device());
        // 00:30 in Warsaw is still the previous day in UTC.
        Instant capturedAt = Instant.parse("2026-10-31T23:30:00Z");

        PresignedUpload upload = service.createUploadUrls(DEVICE, List.of(new Frame(FRAME_ID, capturedAt))).getFirst();

        assertThat(upload.frameId()).isEqualTo(FRAME_ID);
        assertThat(upload.imageKey()).isEqualTo("images/" + DEVICE_ID + "/2026/10/31/" + FRAME_ID + ".jpg");
    }

    @Test
    void theUrlIsAPutOfThatKeyValidFor30MinutesWithASignedContentType() {
        when(deviceLookup.deviceOf(DEVICE)).thenReturn(device());

        PresignedUpload upload = service.createUploadUrls(DEVICE, List.of(new Frame(FRAME_ID, NOW))).getFirst();

        String url = upload.uploadUrl().toString();
        assertThat(url).startsWith("https://images-bucket.s3.eu-central-1.amazonaws.com/" + upload.imageKey());
        assertThat(url).contains("X-Amz-Expires=1800").contains("X-Amz-SignedHeaders=content-type%3Bhost");
        // The presigner signs with the real time, so the expiry is 30 minutes from now, not from the fixed clock.
        assertThat(Duration.between(Instant.now(), upload.expiresAt())).isBetween(Duration.ofMinutes(29), Duration.ofMinutes(31));
    }

    @Test
    void keepsTheOrderOfTheRequest() {
        when(deviceLookup.deviceOf(DEVICE)).thenReturn(device());
        UUID second = UUID.randomUUID();

        List<PresignedUpload> uploads = service.createUploadUrls(DEVICE,
                List.of(new Frame(FRAME_ID, NOW), new Frame(second, NOW)));

        assertThat(uploads).extracting(PresignedUpload::frameId).containsExactly(FRAME_ID, second);
    }

    @Test
    void refusesAFrameCapturedTooLongAgo() {
        when(deviceLookup.deviceOf(DEVICE)).thenReturn(device());
        List<Frame> frames = List.of(new Frame(FRAME_ID, NOW), new Frame(UUID.randomUUID(), NOW.minus(Duration.ofDays(31))));

        assertThatThrownBy(() -> service.createUploadUrls(DEVICE, frames))
                .isInstanceOf(ValidationException.class)
                .extracting(e -> ((ValidationException) e).getViolations(), list(FieldViolation.class))
                .singleElement()
                .satisfies(violation -> {
                    assertThat(violation.index()).isEqualTo(1);
                    assertThat(violation.code()).isEqualTo(ErrorCodes.TIMESTAMP_TOO_OLD);
                });
    }

    @Test
    void aPersonGetsNoUploadUrls() {
        assertThatThrownBy(() -> service.createUploadUrls(new Caller.UserCaller(UUID.randomUUID()),
                List.of(new Frame(FRAME_ID, NOW))))
                .isInstanceOf(ForbiddenException.class);
        verifyNoInteractions(deviceLookup);
    }

    private static Device device() {
        return Device.register(DEVICE_ID, UUID.randomUUID(), "rpi-01", NOW);
    }
}
