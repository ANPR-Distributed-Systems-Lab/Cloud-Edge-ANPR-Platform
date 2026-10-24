package com.anpr.operations.shared.error;

public class NotFoundException extends BusinessException {
    public NotFoundException(String code, String message){
        super(code, message);
    }
}
