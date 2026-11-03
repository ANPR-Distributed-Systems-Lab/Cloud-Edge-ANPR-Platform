package com.anpr.devicemanagement.api.configuration;

import lombok.AccessLevel;
import lombok.NoArgsConstructor;

import java.util.Arrays;

/**
 * The ETag of a configuration is its version: the representation changes exactly when the version does. The device
 * polls with If-None-Match, compared as RFC 9110 prescribes (weak comparison, a list of tags or {@code *}).
 */
@NoArgsConstructor(access = AccessLevel.PRIVATE)
final class ConfigurationETag {
    private static final String WEAK_PREFIX = "W/";

    static String of(long version) {
        return "\"" + version + "\"";
    }

    static boolean matches(String ifNoneMatch, String etag) {
        if (ifNoneMatch == null) {
            return false;
        }
        return Arrays.stream(ifNoneMatch.split(","))
                .map(String::trim)
                .map(tag -> tag.startsWith(WEAK_PREFIX) ? tag.substring(WEAK_PREFIX.length()) : tag)
                .anyMatch(tag -> tag.equals("*") || tag.equals(etag));
    }
}
