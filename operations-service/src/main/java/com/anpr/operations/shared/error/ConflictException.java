package com.anpr.operations.shared.error;

public class ConflictException extends BusinessException{
    public ConflictException(String code, String message) {
        super(code, message);
    }
}
