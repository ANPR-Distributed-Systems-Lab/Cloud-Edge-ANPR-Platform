package com.anpr.devicemanagement.internal.models;

import lombok.AccessLevel;
import lombok.NoArgsConstructor;

/**
 * The key layout of the models bucket, {@code models/{model}/{version}/{file}} with {@code release.json} beside the
 * files (infrastructure/envs/dev/models.tf). ml-models publishes into the same layout, so it is a contract.
 */
@NoArgsConstructor(access = AccessLevel.PRIVATE)
public final class ModelKeys {
    public static final String RELEASE_FILE = "release.json";

    public static String file(ModelName model, String version, String fileName) {
        return "models/" + model.id() + "/" + version + "/" + fileName;
    }

    public static String release(ModelName model, String version) {
        return file(model, version, RELEASE_FILE);
    }
}
