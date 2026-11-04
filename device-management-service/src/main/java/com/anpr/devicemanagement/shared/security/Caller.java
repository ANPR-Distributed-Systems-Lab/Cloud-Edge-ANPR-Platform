package com.anpr.devicemanagement.shared.security;

import com.anpr.devicemanagement.shared.error.ForbiddenException;

import java.util.UUID;

/**
 * Who sent the request, as API Gateway identified them (docs/identity-and-access.md). Every endpoint accepts some
 * kinds only; the {@code as...} methods refuse the others with 403 FORBIDDEN.
 */
public sealed interface Caller {

    /** A person signed in to the web application; {@code accountId} is their Cognito sub. */
    record UserCaller(UUID accountId) implements Caller {
    }

    /** An edge device; {@code deviceId} is the Cognito sub of its account. */
    record DeviceCaller(UUID deviceId) implements Caller {
    }

    /** An administrator calling with AWS Signature V4; {@code principalArn} is the IAM principal (for audit logs). */
    record IamCaller(String principalArn) implements Caller {
    }

    default UserCaller asUser() {
        if (this instanceof UserCaller user) {
            return user;
        }
        throw new ForbiddenException("Only a person may call this endpoint");
    }

    default DeviceCaller asDevice() {
        if (this instanceof DeviceCaller device) {
            return device;
        }
        throw new ForbiddenException("Only a device may call this endpoint");
    }

    default IamCaller asAdministrator() {
        if (this instanceof IamCaller administrator) {
            return administrator;
        }
        throw new ForbiddenException("Only an administrator may call this endpoint");
    }
}
