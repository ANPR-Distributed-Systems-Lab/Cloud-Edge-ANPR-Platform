package com.anpr.devicemanagement.internal.models;

import java.net.URI;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

/** The models of one device, as it downloads them: per model the version and a signed URL per file. */
public record DeviceModels(UUID deviceId, ModelDownload detector, ModelDownload ocr) {

    public record ModelDownload(String version, List<FileDownload> files) {
    }

    /** One file of a version; the device discards a download whose SHA-256 differs. */
    public record FileDownload(String name, String sha256, long sizeBytes, URI url, Instant expiresAt) {
    }
}
