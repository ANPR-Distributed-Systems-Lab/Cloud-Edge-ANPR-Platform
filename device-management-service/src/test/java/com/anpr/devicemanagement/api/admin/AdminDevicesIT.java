package com.anpr.devicemanagement.api.admin;

import com.anpr.devicemanagement.support.ApiTestSupport;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;

import java.util.UUID;

import static org.hamcrest.Matchers.not;
import static org.hamcrest.Matchers.containsString;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.doThrow;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class AdminDevicesIT extends ApiTestSupport {

    @Test
    void createsADeviceForAPersonAndAnnouncesThePairing() throws Exception {
        UUID accountId = UUID.randomUUID();
        UUID deviceId = UUID.randomUUID();
        when(accounts.isPerson(accountId)).thenReturn(true);
        when(accounts.createDevice(eq("rpi-created"), anyString())).thenReturn(deviceId);

        mockMvc.perform(post("/api/v1/admin/devices").with(administrator())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(createDeviceRequest(accountId, "rpi-created")))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.deviceId").value(deviceId.toString()))
                .andExpect(jsonPath("$.accountId").value(accountId.toString()))
                .andExpect(jsonPath("$.username").value("rpi-created"))
                .andExpect(jsonPath("$.createdAt").exists())
                .andExpect(content().string(not(containsString("Secret-password-1"))));

        verify(events).paired(deviceId, accountId, 1L);
        mockMvc.perform(get("/api/v1/device").with(person(accountId)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.deviceId").value(deviceId.toString()));
    }

    @Test
    void aSecondDeviceForTheSameAccountIsAConflict() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();

        mockMvc.perform(post("/api/v1/admin/devices").with(administrator())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(createDeviceRequest(owner.accountId(), "rpi-second")))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("ACCOUNT_HAS_DEVICE"));
    }

    @Test
    void theOwnerMustBeAPerson() throws Exception {
        mockMvc.perform(post("/api/v1/admin/devices").with(administrator())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(createDeviceRequest(UUID.randomUUID(), "rpi-orphan")))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("ACCOUNT_NOT_FOUND"));
    }

    @Test
    void anInvalidUsernameIsRefusedBeforeAnythingIsCreated() throws Exception {
        mockMvc.perform(post("/api/v1/admin/devices").with(administrator())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(createDeviceRequest(UUID.randomUUID(), "RPI 01")))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"))
                .andExpect(jsonPath("$.fields[0].field").value("username"))
                .andExpect(jsonPath("$.fields[0].code").value("PATTERN"));
    }

    @Test
    void onlyAnAdministratorMayCreate() throws Exception {
        mockMvc.perform(post("/api/v1/admin/devices").with(person(UUID.randomUUID()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(createDeviceRequest(UUID.randomUUID(), "rpi-forbidden")))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value("FORBIDDEN"));
    }

    @Test
    void aFailedPublishLeavesNoDeviceBehind() throws Exception {
        UUID accountId = UUID.randomUUID();
        UUID deviceId = UUID.randomUUID();
        when(accounts.isPerson(accountId)).thenReturn(true);
        when(accounts.createDevice(eq("rpi-unpublished"), anyString())).thenReturn(deviceId);
        doThrow(new IllegalStateException("SNS unavailable")).when(events).paired(deviceId, accountId, 1L);

        mockMvc.perform(post("/api/v1/admin/devices").with(administrator())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(createDeviceRequest(accountId, "rpi-unpublished")))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.code").value("INTERNAL_ERROR"))
                .andExpect(content().string(not(containsString("SNS"))));

        verify(accounts).deleteDevice("rpi-unpublished");
        mockMvc.perform(get("/api/v1/device").with(device(deviceId)))
                .andExpect(status().isNotFound());
    }

    @Test
    void deletingADeviceAnnouncesItAndRemovesIt() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();

        mockMvc.perform(delete("/api/v1/admin/devices/{deviceId}", owner.deviceId()).with(administrator()))
                .andExpect(status().isNoContent());

        verify(accounts).deleteDevice(owner.username());
        verify(events).unpaired(owner.deviceId(), 2L);
        mockMvc.perform(get("/api/v1/device/config").with(device(owner.deviceId())))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("DEVICE_NOT_FOUND"));
        mockMvc.perform(delete("/api/v1/admin/devices/{deviceId}", owner.deviceId()).with(administrator()))
                .andExpect(status().isNotFound());
    }
}
