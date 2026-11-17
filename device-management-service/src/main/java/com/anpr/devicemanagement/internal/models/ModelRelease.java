package com.anpr.devicemanagement.internal.models;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

/**
 * A published version of a model: {@code release.json} next to its files, written by ml-models
 * ({@code anpr-publish-model}) and never changed afterwards.
 *
 * @param model   {@link ModelName#id()}
 * @param version e.g. v3
 * @param files   every file the device needs, with what to check the download against
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record ModelRelease(String model, String version, List<File> files) {

    @JsonIgnoreProperties(ignoreUnknown = true)
    public record File(String name, String sha256, long sizeBytes) {
    }
}
