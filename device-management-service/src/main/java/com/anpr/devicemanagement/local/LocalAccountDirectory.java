package com.anpr.devicemanagement.local;

import com.anpr.devicemanagement.internal.provisioning.AccountDirectory;
import com.anpr.devicemanagement.shared.error.ConflictException;
import com.anpr.devicemanagement.shared.error.ErrorCodes;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;

import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Stand-in for the user pool on a developer machine: every account id is a person, and device accounts live in
 * memory only (DynamoDB Local keeps the devices across restarts, this directory does not).
 */
@Slf4j
@Component
@Profile("local")
public class LocalAccountDirectory implements AccountDirectory {
    private final Map<String, UUID> devicesByUsername = new ConcurrentHashMap<>();

    @Override
    public boolean isPerson(UUID accountId) {
        return true;
    }

    @Override
    public UUID createDevice(String username, String password) {
        UUID deviceId = UUID.randomUUID();
        if (devicesByUsername.putIfAbsent(username, deviceId) != null) {
            throw new ConflictException(ErrorCodes.USERNAME_TAKEN, "Username is already taken");
        }
        log.atInfo().addKeyValue("deviceId", deviceId).addKeyValue("username", username).log("Local device account created");
        return deviceId;
    }

    @Override
    public void deleteDevice(String username) {
        devicesByUsername.remove(username);
    }
}
