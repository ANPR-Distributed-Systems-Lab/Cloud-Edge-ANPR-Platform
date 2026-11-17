package com.anpr.devicemanagement.shared.error;

import lombok.AccessLevel;
import lombok.NoArgsConstructor;

/** Values of {@code code} in error responses. They are part of the contract: clients react to them, not to messages. */
@NoArgsConstructor(access = AccessLevel.PRIVATE)
public final class ErrorCodes {
    public static final String VALIDATION_FAILED = "VALIDATION_FAILED";
    public static final String INVALID_REQUEST = "INVALID_REQUEST";
    public static final String UNAUTHENTICATED = "UNAUTHENTICATED";
    public static final String FORBIDDEN = "FORBIDDEN";
    public static final String DEVICE_NOT_FOUND = "DEVICE_NOT_FOUND";
    public static final String ACCOUNT_NOT_FOUND = "ACCOUNT_NOT_FOUND";
    public static final String ACCOUNT_HAS_DEVICE = "ACCOUNT_HAS_DEVICE";
    public static final String USERNAME_TAKEN = "USERNAME_TAKEN";
    public static final String CONCURRENT_MODIFICATION = "CONCURRENT_MODIFICATION";
    /** A configuration names a model version that is not published (409, or a field code of a 400). */
    public static final String MODEL_NOT_PUBLISHED = "MODEL_NOT_PUBLISHED";
    public static final String INTERNAL_ERROR = "INTERNAL_ERROR";

    // Field codes in fields[] of VALIDATION_FAILED, the same names as in the ingest Lambda.
    public static final String REQUIRED = "REQUIRED";
    public static final String RANGE = "RANGE";
    public static final String SIZE = "SIZE";
    public static final String PATTERN = "PATTERN";
    public static final String TIMESTAMP_IN_FUTURE = "TIMESTAMP_IN_FUTURE";
    public static final String TIMESTAMP_TOO_OLD = "TIMESTAMP_TOO_OLD";
    public static final String DUPLICATE_RECORDED_AT = "DUPLICATE_RECORDED_AT";
    public static final String PASSWORD_POLICY = "PASSWORD_POLICY";
}
