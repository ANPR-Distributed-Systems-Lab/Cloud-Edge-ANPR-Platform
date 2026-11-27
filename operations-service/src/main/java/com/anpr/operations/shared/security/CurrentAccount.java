package com.anpr.operations.shared.security;

import com.anpr.operations.shared.error.ErrorCodes;
import com.anpr.operations.shared.error.UnauthorizedException;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;

import java.util.UUID;

@Component
@RequiredArgsConstructor
public class CurrentAccount {
    static final String ACCOUNT_HEADER = "X-Account-Id";
    static final String ACCOUNT_TYPE_HEADER = "X-Account-Type";
    static final String DEVICE_ACCOUNT_TYPE = "device";
    private final HttpServletRequest request;

    public boolean isDevice() {
        return DEVICE_ACCOUNT_TYPE.equals(request.getHeader(ACCOUNT_TYPE_HEADER));
    }

    public UUID id() {
        String value = request.getHeader(ACCOUNT_HEADER);
        if (value == null || value.isBlank()) {
            throw new UnauthorizedException(ErrorCodes.UNAUTHENTICATED, "Missing account header");
        }
        try {
            return UUID.fromString(value);
        } catch (IllegalArgumentException e) {
            throw new UnauthorizedException(ErrorCodes.UNAUTHENTICATED, "Invalid account header");
        }
    }
}
