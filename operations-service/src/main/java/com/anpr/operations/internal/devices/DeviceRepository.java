package com.anpr.operations.internal.devices;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;

import java.util.Optional;
import java.util.UUID;

public interface DeviceRepository extends JpaRepository<Device, UUID> {
    @Query("SELECT d.accountId FROM Device d WHERE d.deviceId = :deviceId")
    Optional<UUID> findOwnerById(UUID deviceId);
}
