package com.anpr.operations.internal.devices;

import com.anpr.operations.internal.accounts.AccountRepository;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Optional;
import java.util.UUID;

/**
 * Applies the device events of device-management (docs/events/device-events.md). Delivery is at-least-once and
 * unordered, so an event is applied only when its version is newer than the stored one.
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DevicePairingService {
    private final DeviceRepository deviceRepository;
    private final AccountRepository accountRepository;

    @Transactional
    public void pair(UUID deviceId, UUID accountId, long version) {
        Optional<Device> stored = deviceRepository.findById(deviceId);
        if (stored.isPresent() && !stored.get().isOlderThan(version)) {
            log.debug("Ignored device.paired of device {} with version {}", deviceId, version);
            return;
        }
        // The account first: devices.account_id references accounts.
        accountRepository.insertIfAbsent(accountId);
        stored.ifPresentOrElse(
                device -> device.pair(accountId, version),
                () -> deviceRepository.save(Device.paired(deviceId, accountId, version)));
    }

    @Transactional
    public void unpair(UUID deviceId, long version) {
        Optional<Device> stored = deviceRepository.findById(deviceId);
        if (stored.isEmpty()) {
            // The unpairing arrived before its pairing: remember the version so the late pairing is ignored.
            deviceRepository.save(Device.unpaired(deviceId, version));
            return;
        }
        Device device = stored.get();
        if (!device.isOlderThan(version)) {
            log.debug("Ignored device.unpaired of device {} with version {}", deviceId, version);
            return;
        }
        device.unpair(version);
    }
}
