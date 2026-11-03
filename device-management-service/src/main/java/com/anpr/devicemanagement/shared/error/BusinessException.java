package com.anpr.devicemanagement.shared.error;

import lombok.Getter;

/**
 * A request refused because of the client: the response carries {@link #getCode()} and the status of the subclass.
 */
@Getter
public abstract class BusinessException extends RuntimeException {
    private final String code;

    protected BusinessException(String code, String message) {
        super(message);
        this.code = code;
    }
}
