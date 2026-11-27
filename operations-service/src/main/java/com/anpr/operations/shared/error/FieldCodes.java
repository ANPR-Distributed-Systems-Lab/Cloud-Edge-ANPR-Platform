package com.anpr.operations.shared.error;

/** Field codes in fields[] of VALIDATION_FAILED, the same in every service and the ingest Lambda. */
public enum FieldCodes {
    REQUIRED,
    RANGE,
    SIZE,
    PATTERN
}
