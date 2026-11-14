package com.anpr.devicemanagement.internal.images;

import com.anpr.devicemanagement.config.AwsProperties;
import com.anpr.devicemanagement.internal.devices.DeviceLookup;
import com.anpr.devicemanagement.shared.error.FieldViolation;
import com.anpr.devicemanagement.shared.error.TechnicalException;
import com.anpr.devicemanagement.shared.error.ValidationException;
import com.anpr.devicemanagement.shared.security.Caller;
import com.anpr.devicemanagement.shared.validation.TimestampWindow;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;
import software.amazon.awssdk.services.s3.presigner.model.PresignedPutObjectRequest;

import java.net.URISyntaxException;
import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/**
 * Presigned URLs for the photos of detections. The key layout is fixed by the contract and the device computes it
 * for its detections; the key signed here is always under the prefix of the caller, so a device cannot upload to the
 * prefix of another one, and the ingest Lambda refuses a detection with a key of another device.
 */
@Service
public class ImageUploadService {
    private final DeviceLookup deviceLookup;
    private final S3Presigner presigner;
    private final String bucket;
    private final ImagesProperties properties;
    private final TimestampWindow window;
    private final Clock clock;

    public ImageUploadService(DeviceLookup deviceLookup, S3Presigner presigner, AwsProperties aws,
                              ImagesProperties properties, Clock clock) {
        this.deviceLookup = deviceLookup;
        this.presigner = presigner;
        this.bucket = aws.s3().imagesBucket();
        this.properties = properties;
        this.window = new TimestampWindow(properties.maxCaptureAge(), properties.maxClockSkew());
        this.clock = clock;
    }

    /** One upload per frame, in the order of the request; the frames are validated as a whole (all or nothing). */
    public List<PresignedUpload> createUploadUrls(Caller caller, List<Frame> frames) {
        caller.asDevice();
        UUID deviceId = deviceLookup.deviceOf(caller).getDeviceId();
        validate(frames, clock.instant());

        return frames.stream().map(frame -> presign(ImageKeys.of(deviceId, frame), frame)).toList();
    }

    /**
     * The URL signs the content type, so the upload must send exactly {@code Content-Type: image/jpeg}. The URL
     * carries the permissions of the task role, which may put objects under images/ only.
     */
    private PresignedUpload presign(String key, Frame frame) {
        PresignedPutObjectRequest presigned = presigner.presignPutObject(request -> request
                .signatureDuration(properties.uploadUrlValidity())
                .putObjectRequest(put -> put.bucket(bucket).key(key).contentType(MediaType.IMAGE_JPEG_VALUE)));
        try {
            return new PresignedUpload(frame.frameId(), key, presigned.url().toURI(), presigned.expiration());
        } catch (URISyntaxException e) {
            throw new TechnicalException("The presigner returned an invalid URL", e);
        }
    }

    private void validate(List<Frame> frames, Instant now) {
        List<FieldViolation> violations = new ArrayList<>();
        for (int i = 0; i < frames.size(); i++) {
            window.check(frames.get(i).capturedAt(), now, i, "frames[" + i + "].capturedAt").ifPresent(violations::add);
        }
        if (!violations.isEmpty()) {
            throw new ValidationException(violations);
        }
    }
}
