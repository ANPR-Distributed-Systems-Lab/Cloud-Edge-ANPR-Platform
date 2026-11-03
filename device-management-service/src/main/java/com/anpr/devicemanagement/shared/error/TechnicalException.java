package com.anpr.devicemanagement.shared.error;

/** A failure on our side (inconsistent data, a dependency that keeps failing). Answered with 500 and logged at ERROR. */
public class TechnicalException extends RuntimeException {
    public TechnicalException(String message) {
        super(message);
    }

    public TechnicalException(String message, Throwable cause) {
        super(message, cause);
    }
}
