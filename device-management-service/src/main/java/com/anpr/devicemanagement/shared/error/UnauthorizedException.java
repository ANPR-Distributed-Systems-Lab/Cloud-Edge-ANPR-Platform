package com.anpr.devicemanagement.shared.error;

/** The identity headers of API Gateway are missing or malformed: the request did not come through the gateway. */
public class UnauthorizedException extends BusinessException {
    public UnauthorizedException(String message) {
        super(ErrorCodes.UNAUTHENTICATED, message);
    }
}
