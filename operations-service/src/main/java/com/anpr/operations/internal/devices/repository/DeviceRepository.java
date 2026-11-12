package com.anpr.operations.internal.devices.repository;

import com.anpr.operations.internal.devices.model.Device;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.util.Optional;
import java.util.UUID;

public interface DeviceRepository extends JpaRepository<Device, UUID> {
    @Query("SELECT d.accountId FROM Device d WHERE d.deviceId = :deviceId")
    Optional<UUID> findOwnerById(UUID deviceId);

    /** The device currently paired with the account; an account has at most one (uq_devices_account). */
    @Query("SELECT d.deviceId FROM Device d WHERE d.accountId = :accountId")
    Optional<UUID> findPairedDeviceId(UUID accountId);
}
