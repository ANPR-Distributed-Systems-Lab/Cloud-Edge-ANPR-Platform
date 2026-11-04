package com.anpr.devicemanagement.internal.provisioning;

import java.util.UUID;

/**
 * What an administrator provides to create a device.
 *
 * @param accountId the person who becomes the owner
 * @param username  login of the device in Cognito
 * @param password  initial password of the device; never stored or logged
 */
public record NewDevice(UUID accountId, String username, String password) {

    /** Keeps the password out of logs and exception messages. */
    @Override
    public String toString() {
        return "NewDevice[accountId=" + accountId + ", username=" + username + "]";
    }
}
