package com.anpr.operations.shared.error;

/**
 * One problem in the request: an item of fields[] in VALIDATION_FAILED. Without the batch index of device-management,
 * because no endpoint of this service accepts a batch.
 *
 * @param field   name of the parameter or path of the body field, e.g. {@code to} or {@code plate}
 * @param code    one of {@link FieldCodes}, or the upper-cased Bean Validation constraint name for any other
 * @param message human-readable explanation
 */
public record FieldViolation(String field, String code, String message) {
}
