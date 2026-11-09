package com.anpr.operations.shared.storage;

import com.anpr.operations.config.AwsProperties;
import org.mapstruct.Named;
import org.springframework.stereotype.Component;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;

import java.net.URI;
import java.net.URISyntaxException;

/**
 * Presigned GET URLs of the detection photos. The bucket stays private: a URL opens one photo for a short time.
 * Shared because every view that returns detections (search, radial analysis, live feed) carries the photo.
 */
@Component
public class ImageUrlSigner {
    private final S3Presigner presigner;
    private final AwsProperties.S3 s3;

    public ImageUrlSigner(S3Presigner presigner, AwsProperties aws) {
        this.presigner = presigner;
        this.s3 = aws.s3();
    }

    /** The URL carries the permissions of the task role, which may read objects under images/ only. */
    @Named("imageUrl")
    public URI urlOf(String imageKey) {
        String url = presigner.presignGetObject(request -> request
                        .signatureDuration(s3.imageUrlValidity())
                        .getObjectRequest(get -> get.bucket(s3.imagesBucket()).key(imageKey)))
                .url().toString();
        try {
            return new URI(url);
        } catch (URISyntaxException e) {
            throw new IllegalStateException("The presigner returned an invalid URL", e);
        }
    }
}