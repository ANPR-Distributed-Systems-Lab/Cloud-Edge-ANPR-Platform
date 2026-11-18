package com.anpr.operations.shared.error;

public class ForbiddenException extends BusinessException{
    public ForbiddenException(ErrorCodes code, String message) {
        super(code, message);
    }
}
