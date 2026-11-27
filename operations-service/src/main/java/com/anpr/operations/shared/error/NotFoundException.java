package com.anpr.operations.shared.error;

public class NotFoundException extends BusinessException {
    public NotFoundException(ErrorCodes code, String message) {
        super(code, message);
    }
}
