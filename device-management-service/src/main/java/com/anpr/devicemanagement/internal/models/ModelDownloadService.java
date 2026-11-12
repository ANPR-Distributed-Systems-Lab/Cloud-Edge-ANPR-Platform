package com.anpr.devicemanagement.internal.models;

import com.anpr.devicemanagement.config.AwsProperties;
import com.anpr.devicemanagement.internal.configuration.ConfigurationService;
import com.anpr.devicemanagement.internal.configuration.DeviceConfiguration;
import com.anpr.devicemanagement.internal.configuration.DeviceSettings;
import com.anpr.devicemanagement.shared.error.TechnicalException;
import com.anpr.devicemanagement.shared.security.Caller;
import org.springframework.stereotype.Service;
import software.amazon.awssdk.services.s3.presigner.S3Presigner;
import software.amazon.awssdk.services.s3.presigner.model.PresignedGetObjectRequest;

import java.net.URISyntaxException;

/**
 * Download URLs of the models a device runs. The configuration decides the versions, so a device can only download
 * what its owner chose, and never names a version or a key itself.
 */
@Service
public class ModelDownloadService {
    private final ConfigurationService configurations;
    private final PublishedModels publishedModels;
    private final S3Presigner presigner;
    private final String bucket;
    private final ModelsProperties properties;

    public ModelDownloadService(ConfigurationService configurations, PublishedModels publishedModels,
                                S3Presigner presigner, AwsProperties aws, ModelsProperties properties) {
        this.configurations = configurations;
        this.publishedModels = publishedModels;
        this.presigner = presigner;
        this.bucket = aws.s3().modelsBucket();
        this.properties = properties;
    }

    public DeviceModels downloads(Caller caller) {
        caller.asDevice();
        DeviceConfiguration configuration = configurations.get(caller);
        DeviceSettings.Models models = configuration.getSettings().getModels();
        return new DeviceModels(configuration.getDeviceId(),
                download(ModelName.DETECTOR, ModelName.DETECTOR.versionIn(models)),
                download(ModelName.OCR, ModelName.OCR.versionIn(models)));
    }

    private DeviceModels.ModelDownload download(ModelName model, String version) {
        ModelRelease release = publishedModels.release(model, version);
        return new DeviceModels.ModelDownload(version, release.files().stream()
                .map(file -> presign(model, version, file))
                .toList());
    }

    /** The URL carries the permissions of the task role, which may read objects under models/ only. */
    private DeviceModels.FileDownload presign(ModelName model, String version, ModelRelease.File file) {
        PresignedGetObjectRequest presigned = presigner.presignGetObject(request -> request
                .signatureDuration(properties.downloadUrlValidity())
                .getObjectRequest(get -> get.bucket(bucket).key(ModelKeys.file(model, version, file.name()))));
        try {
            return new DeviceModels.FileDownload(file.name(), file.sha256(), file.sizeBytes(),
                    presigned.url().toURI(), presigned.expiration());
        } catch (URISyntaxException e) {
            throw new TechnicalException("The presigner returned an invalid URL", e);
        }
    }
}
