package com.anpr.operations.shared.error;

public class UnauthorizedException extends BusinessException {
    public UnauthorizedException(String code, String message) {
        super(code, message);
    }
}
