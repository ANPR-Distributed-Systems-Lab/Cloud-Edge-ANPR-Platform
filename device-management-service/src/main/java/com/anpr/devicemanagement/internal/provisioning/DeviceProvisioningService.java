package com.anpr.devicemanagement.internal.provisioning;

import com.anpr.devicemanagement.internal.configuration.DefaultSettings;
import com.anpr.devicemanagement.internal.configuration.DeviceConfiguration;
import com.anpr.devicemanagement.internal.devices.Device;
import com.anpr.devicemanagement.internal.devices.DeviceRepository;
import com.anpr.devicemanagement.shared.error.ConflictException;
import com.anpr.devicemanagement.shared.error.ErrorCodes;
import com.anpr.devicemanagement.shared.error.NotFoundException;
import com.anpr.devicemanagement.shared.security.Caller;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.Clock;
import java.time.Instant;
import java.util.UUID;

/**
 * Creating and deleting devices (administrator only). A device spans three systems: its Cognito account, its records
 * in DynamoDB and the copies other services keep from the device events. There is no transaction across them, so
 * each operation orders its steps to stay consistent when one fails (docs/device-management.md).
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DeviceProvisioningService {
    private final AccountDirectory accounts;
    private final DeviceRepository devices;
    private final DeviceRecords records;
    private final DeviceEvents events;
    private final DefaultSettings defaultSettings;
    private final Clock clock;

    /**
     * Creates the account of the device, its registration with the owner and its default configuration, then
     * announces the pairing. All or nothing: when a later step fails, the earlier ones are undone.
     */
    public Device create(Caller caller, NewDevice request) {
        caller.asAdministrator();
        if (!accounts.isPerson(request.accountId())) {
            throw new NotFoundException(ErrorCodes.ACCOUNT_NOT_FOUND, "Account not found or not a person");
        }
        // Read from an eventually consistent index: two creations for one account within a second could both pass.
        if (devices.findByAccountId(request.accountId()).isPresent()) {
            throw new ConflictException(ErrorCodes.ACCOUNT_HAS_DEVICE, "The account already has a device");
        }

        UUID deviceId = accounts.createDevice(request.username(), request.password());
        Instant now = clock.instant();
        Device device = Device.register(deviceId, request.accountId(), request.username(), now);
        try {
            records.insert(device, DeviceConfiguration.initial(deviceId, defaultSettings.newSettings(), now));
            events.paired(deviceId, device.getAccountId(), device.getVersion());
        } catch (RuntimeException e) {
            undoCreate(device, e);
            throw e;
        }

        log.atInfo().addKeyValue("deviceId", deviceId).addKeyValue("accountId", device.getAccountId())
                .log("Device created");
        return device;
    }

    /**
     * Deletes the account of the device first (no new tokens), announces the end of the pairing, and deletes the
     * records last. Every step is idempotent and the registration is what a repeated request finds, so repeating a
     * failed deletion finishes it.
     */
    public void delete(Caller caller, UUID deviceId) {
        caller.asAdministrator();
        Device device = devices.findById(deviceId)
                .orElseThrow(() -> new NotFoundException(ErrorCodes.DEVICE_NOT_FOUND, "Device not found"));

        accounts.deleteDevice(device.getUsername());
        events.unpaired(deviceId, device.unpairedVersion());
        records.remove(deviceId);

        log.atInfo().addKeyValue("deviceId", deviceId).addKeyValue("accountId", device.getAccountId())
                .log("Device deleted");
    }

    /**
     * Best effort, step by step: what cannot be undone is logged with how to clean it up, and the original failure
     * is still the one reported. If the publish timed out after SNS accepted it, consumers keep the pairing of a
     * device that no longer exists (and can no longer sign in).
     */
    private void undoCreate(Device device, RuntimeException cause) {
        log.atWarn().addKeyValue("deviceId", device.getDeviceId()).log("Device creation failed, undoing it");
        try {
            records.remove(device.getDeviceId());
        } catch (RuntimeException undoFailure) {
            cause.addSuppressed(undoFailure);
            log.atError().setCause(undoFailure).addKeyValue("deviceId", device.getDeviceId())
                    .log("Records of a failed device creation left behind; deleting the device removes them");
        }
        try {
            accounts.deleteDevice(device.getUsername());
        } catch (RuntimeException undoFailure) {
            cause.addSuppressed(undoFailure);
            log.atError().setCause(undoFailure).addKeyValue("username", device.getUsername())
                    .log("Cognito user of a failed device creation left behind; delete it in the user pool");
        }
    }
}
