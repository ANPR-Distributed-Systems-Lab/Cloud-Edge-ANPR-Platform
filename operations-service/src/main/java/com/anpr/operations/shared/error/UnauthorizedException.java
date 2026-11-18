package com.anpr.operations.shared.error;

public class UnauthorizedException extends BusinessException {
    public UnauthorizedException(ErrorCodes code, String message) {
        super(code, message);
    }
}
