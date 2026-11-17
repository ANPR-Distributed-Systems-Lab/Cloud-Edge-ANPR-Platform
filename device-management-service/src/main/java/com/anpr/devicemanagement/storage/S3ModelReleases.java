package com.anpr.devicemanagement.storage;

import com.anpr.devicemanagement.config.AwsProperties;
import com.anpr.devicemanagement.internal.models.ModelKeys;
import com.anpr.devicemanagement.internal.models.ModelName;
import com.anpr.devicemanagement.internal.models.ModelRelease;
import com.anpr.devicemanagement.internal.models.ModelReleases;
import com.anpr.devicemanagement.shared.error.TechnicalException;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;
import software.amazon.awssdk.services.s3.S3Client;
import software.amazon.awssdk.services.s3.model.NoSuchKeyException;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.json.JsonMapper;

import java.util.Objects;
import java.util.Optional;
import java.util.regex.Pattern;

/**
 * Reads {@code release.json} of a model version from the models bucket. The file is written by ml-models, so its
 * content is checked before any of it becomes an S3 key or reaches a device.
 */
@Component
@Profile("!local")
public class S3ModelReleases implements ModelReleases {
    private static final Pattern FILE_NAME = Pattern.compile("[A-Za-z0-9][A-Za-z0-9._-]{0,63}");
    private static final Pattern SHA256 = Pattern.compile("[0-9a-f]{64}");

    private final S3Client s3;
    private final String bucket;
    private final JsonMapper jsonMapper;

    public S3ModelReleases(S3Client s3, AwsProperties aws, JsonMapper jsonMapper) {
        this.s3 = s3;
        this.bucket = aws.s3().modelsBucket();
        this.jsonMapper = jsonMapper;
    }

    @Override
    public Optional<ModelRelease> find(ModelName model, String version) {
        String key = ModelKeys.release(model, version);
        byte[] body;
        try {
            body = s3.getObjectAsBytes(request -> request.bucket(bucket).key(key)).asByteArray();
        } catch (NoSuchKeyException e) {
            return Optional.empty();
        }
        try {
            return Optional.of(checked(jsonMapper.readValue(body, ModelRelease.class), model, version, key));
        } catch (JacksonException e) {
            throw new TechnicalException(key + " is not a valid release description", e);
        }
    }

    private static ModelRelease checked(ModelRelease release, ModelName model, String version, String key) {
        boolean valid = Objects.equals(release.model(), model.id())
                && Objects.equals(release.version(), version)
                && release.files() != null && !release.files().isEmpty()
                && release.files().stream().allMatch(file -> file.name() != null
                && FILE_NAME.matcher(file.name()).matches()
                && !file.name().equals(ModelKeys.RELEASE_FILE)
                && file.sha256() != null && SHA256.matcher(file.sha256()).matches()
                && file.sizeBytes() >= 0);
        if (!valid) {
            throw new TechnicalException(key + " does not describe " + model.id() + " " + version + " correctly");
        }
        return release;
    }
}
