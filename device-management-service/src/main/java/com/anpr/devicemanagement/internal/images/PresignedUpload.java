package com.anpr.devicemanagement.internal.images;

import java.net.URI;
import java.time.Instant;
import java.util.UUID;

/** Where the photo of a frame goes ({@code imageKey}) and the signed URL to put it there until {@code expiresAt}. */
public record PresignedUpload(UUID frameId, String imageKey, URI uploadUrl, Instant expiresAt) {
}
