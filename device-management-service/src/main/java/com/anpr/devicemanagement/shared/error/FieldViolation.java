package com.anpr.devicemanagement.shared.error;

/**
 * One problem in the request body.
 *
 * @param index   position of the item in a batch, null for errors about the request itself
 * @param field   path of the field, e.g. {@code metrics[3].recordedAt}
 * @param code    stable code, e.g. {@code TIMESTAMP_TOO_OLD}
 * @param message human-readable explanation
 */
public record FieldViolation(Integer index, String field, String code, String message) {
}
