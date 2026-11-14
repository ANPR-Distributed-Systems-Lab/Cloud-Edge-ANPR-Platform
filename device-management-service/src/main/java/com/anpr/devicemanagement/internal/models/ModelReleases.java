package com.anpr.devicemanagement.internal.models;

import java.util.Optional;

/** Where the published model versions are described (the models bucket in AWS). */
public interface ModelReleases {

    /** The release of the version, or empty when that version is not published. */
    Optional<ModelRelease> find(ModelName model, String version);
}
