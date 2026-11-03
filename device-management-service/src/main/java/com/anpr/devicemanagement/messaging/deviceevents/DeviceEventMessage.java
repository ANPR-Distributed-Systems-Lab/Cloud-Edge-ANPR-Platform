package com.anpr.devicemanagement.messaging.deviceevents;

import com.fasterxml.jackson.annotation.JsonInclude;

/**
 * Body of a message on the device-events topic, field by field as in docs/events/device-events.md.
 *
 * @param accountId the owner, only in device.paired
 */
@JsonInclude(JsonInclude.Include.NON_NULL)
record DeviceEventMessage(String eventId, String occurredAt, long version, String deviceId, String accountId) {
}
