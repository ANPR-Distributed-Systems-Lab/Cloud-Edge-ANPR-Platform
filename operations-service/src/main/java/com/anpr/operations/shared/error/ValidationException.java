package com.anpr.operations.shared.error;

import lombok.Getter;

import java.util.List;

/**
 * Input that is well-formed but breaks a rule checked by the service (e.g. a time range longer than a view allows).
 * Lists every violation found, not only the first.
 */
@Getter
public class ValidationException extends BusinessException {
    private final List<FieldViolation> violations;

    public ValidationException(List<FieldViolation> violations) {
        super(ErrorCodes.VALIDATION_FAILED, violations.size() + " validation error(s), nothing was accepted");
        this.violations = List.copyOf(violations);
    }

    public static ValidationException of(FieldViolation violation) {
        return new ValidationException(List.of(violation));
    }
}
