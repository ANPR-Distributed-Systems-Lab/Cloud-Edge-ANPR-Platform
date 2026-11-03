package com.anpr.devicemanagement.shared.error;

/** The caller is authenticated, but its kind (person, device, administrator) may not call the endpoint. */
public class ForbiddenException extends BusinessException {
    public ForbiddenException(String message) {
        super(ErrorCodes.FORBIDDEN, message);
    }
}
