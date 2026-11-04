package com.anpr.operations.shared.error;

import lombok.AccessLevel;
import lombok.NoArgsConstructor;

@NoArgsConstructor(access = AccessLevel.PRIVATE)
public final class ErrorCodes {
    public static final String VALIDATION_FAILED = "VALIDATION_FAILED";
    public static final  String ALERT_ALREADY_EXISTS = "ALERT_ALREADY_EXISTS";
    public static final String CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION";
    public static final String INTERNAL_ERROR = "INTERNAL_ERROR";
    public static final String UNAUTHENTICATED = "UNAUTHENTICATED";
    public static final String ALERT_NOT_FOUND = "ALERT_NOT_FOUND";
    public static final String INVALID_REQUEST = "INVALID_REQUEST";

    // Field codes in fields[] of VALIDATION_FAILED, the same in every service and the ingest Lambda.
    public static final String REQUIRED = "REQUIRED";
    public static final String RANGE = "RANGE";
    public static final String SIZE = "SIZE";
    public static final String PATTERN = "PATTERN";
}