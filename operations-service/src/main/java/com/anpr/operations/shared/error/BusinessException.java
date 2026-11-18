package com.anpr.operations.shared.error;

import lombok.Getter;

@Getter
public abstract class BusinessException extends RuntimeException{
    private final ErrorCodes code;

    protected BusinessException(ErrorCodes code, String message) {
        super(message);
        this.code = code;
    }
}
