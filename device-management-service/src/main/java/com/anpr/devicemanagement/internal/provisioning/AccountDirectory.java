package com.anpr.devicemanagement.internal.provisioning;

import com.anpr.devicemanagement.shared.error.ConflictException;
import com.anpr.devicemanagement.shared.error.ValidationException;

import java.util.UUID;

/** The accounts of people and devices (the Cognito user pool), as the provisioning needs them. */
public interface AccountDirectory {

    /** Whether the account exists and belongs to a person (the group of users). */
    boolean isPerson(UUID accountId);

    /**
     * Creates the account of a device with a permanent password, in the group of devices. Either the whole account
     * is created or nothing is left behind.
     *
     * @return the device id, i.e. the Cognito sub of the new account
     * @throws ConflictException   USERNAME_TAKEN
     * @throws ValidationException PASSWORD_POLICY when the password does not meet the policy of the user pool
     */
    UUID createDevice(String username, String password);

    /** Deletes the account of a device; does nothing if it does not exist (any more). */
    void deleteDevice(String username);
}
