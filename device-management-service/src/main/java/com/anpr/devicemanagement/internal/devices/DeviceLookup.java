package com.anpr.devicemanagement.internal.devices;

import com.anpr.devicemanagement.shared.error.ErrorCodes;
import com.anpr.devicemanagement.shared.error.ForbiddenException;
import com.anpr.devicemanagement.shared.error.NotFoundException;
import com.anpr.devicemanagement.shared.security.Caller;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

/**
 * The device a request is about. It is never named by the client: a device acts on itself, a person on the device of
 * their account. A device that is not registered (e.g. deleted while its token is still valid) is not found.
 */
@Service
@RequiredArgsConstructor
public class DeviceLookup {
    private final DeviceRepository devices;

    public Device deviceOf(Caller caller) {
        return (switch (caller) {
            case Caller.UserCaller user -> devices.findByAccountId(user.accountId());
            case Caller.DeviceCaller device -> devices.findById(device.deviceId());
            case Caller.IamCaller administrator -> throw new ForbiddenException("An administrator has no device");
        }).orElseThrow(() -> new NotFoundException(ErrorCodes.DEVICE_NOT_FOUND, "Device not found"));
    }
}
