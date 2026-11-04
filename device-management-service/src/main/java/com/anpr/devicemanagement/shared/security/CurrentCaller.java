package com.anpr.devicemanagement.shared.security;

import com.anpr.devicemanagement.shared.error.UnauthorizedException;
import jakarta.servlet.http.HttpServletRequest;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.util.UUID;

/**
 * Reads the caller of the current request from the headers API Gateway injects (and overwrites when a client sends
 * them). The service is reachable only through the gateway, so the headers are trusted.
 */
@Component
@RequiredArgsConstructor
public class CurrentCaller {
    static final String ACCOUNT_ID_HEADER = "X-Account-Id";
    static final String ACCOUNT_TYPE_HEADER = "X-Account-Type";

    private final HttpServletRequest request;

    public Caller get() {
        String type = request.getHeader(ACCOUNT_TYPE_HEADER);
        String id = request.getHeader(ACCOUNT_ID_HEADER);
        if (!StringUtils.hasText(type) || !StringUtils.hasText(id)) {
            throw new UnauthorizedException("Missing identity headers");
        }
        return switch (type) {
            case "user" -> new Caller.UserCaller(parseUuid(id));
            case "device" -> new Caller.DeviceCaller(parseUuid(id));
            case "iam" -> new Caller.IamCaller(id);
            default -> throw new UnauthorizedException("Unknown account type");
        };
    }

    private static UUID parseUuid(String value) {
        try {
            return UUID.fromString(value);
        } catch (IllegalArgumentException e) {
            throw new UnauthorizedException("Invalid account id");
        }
    }
}
