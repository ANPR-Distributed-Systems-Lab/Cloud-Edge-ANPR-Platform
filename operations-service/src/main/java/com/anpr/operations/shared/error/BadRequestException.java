package com.anpr.operations.shared.error;

public class BadRequestException extends BusinessException {
    public BadRequestException(ErrorCodes code, String message) {
        super(code, message);
    }
}
