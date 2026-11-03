package com.anpr.devicemanagement.internal.metrics;

import com.anpr.devicemanagement.internal.devices.Device;
import com.anpr.devicemanagement.internal.devices.DeviceLookup;
import com.anpr.devicemanagement.shared.error.ErrorCodes;
import com.anpr.devicemanagement.shared.error.FieldViolation;
import com.anpr.devicemanagement.shared.error.ValidationException;
import com.anpr.devicemanagement.shared.security.Caller;
import com.anpr.devicemanagement.shared.validation.TimestampWindow;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

/** View 5: the device reports its health, the owner charts it. */
@Slf4j
@Service
public class MetricsService {
    private final DeviceLookup deviceLookup;
    private final MeasurementRepository measurements;
    private final MetricsProperties properties;
    private final TimestampWindow window;
    private final Clock clock;

    public MetricsService(DeviceLookup deviceLookup, MeasurementRepository measurements, MetricsProperties properties,
                          Clock clock) {
        this.deviceLookup = deviceLookup;
        this.measurements = measurements;
        this.properties = properties;
        this.window = new TimestampWindow(properties.retention(), properties.maxClockSkew());
        this.clock = clock;
    }

    /** Stores a batch of measurements of the calling device; the batch is validated as a whole (all or nothing). */
    public void report(Caller caller, List<Measurement> batch) {
        caller.asDevice();
        Device device = deviceLookup.deviceOf(caller);
        validate(batch, clock.instant());

        batch.forEach(measurement -> measurement.storeFor(device.getDeviceId(), properties.retention()));
        measurements.saveAll(batch);
        log.atDebug().addKeyValue("deviceId", device.getDeviceId()).addKeyValue("count", batch.size())
                .log("Measurements stored");
    }

    /**
     * The {@code limit} most recent measurements of the owner's device within the retention, optionally only those
     * recorded before {@code before}, ordered by recordedAt ascending.
     */
    public DeviceMeasurements latest(Caller caller, int limit, Instant before) {
        caller.asUser();
        UUID deviceId = deviceLookup.deviceOf(caller).getDeviceId();
        Instant now = clock.instant();
        Instant to = before != null ? before : latestAcceptedMoment(now);

        List<Measurement> newestFirst = measurements.findLatest(deviceId, oldestKeptMoment(now), to, limit);
        return new DeviceMeasurements(deviceId, newestFirst.reversed());
    }

    /** The most recent measurement of a device within the retention, if any. */
    public Optional<Measurement> lastMeasurement(UUID deviceId) {
        Instant now = clock.instant();
        return measurements.findLatest(deviceId, oldestKeptMoment(now), latestAcceptedMoment(now), 1).stream().findFirst();
    }

    private Instant oldestKeptMoment(Instant now) {
        return now.minus(properties.retention());
    }

    /** Exclusive bound just after the newest recordedAt that may be stored (a device clock ahead of ours). */
    private Instant latestAcceptedMoment(Instant now) {
        return now.plus(properties.maxClockSkew()).plusMillis(1);
    }

    private void validate(List<Measurement> batch, Instant now) {
        List<FieldViolation> violations = new ArrayList<>();
        Set<Long> seen = new HashSet<>();
        for (int i = 0; i < batch.size(); i++) {
            String field = "metrics[" + i + "].recordedAt";
            Instant recordedAt = batch.get(i).getRecordedAt();
            window.check(recordedAt, now, i, field).ifPresent(violations::add);
            // The table keeps milliseconds, and one batch write may not hold the same key twice.
            if (!seen.add(recordedAt.toEpochMilli())) {
                violations.add(new FieldViolation(i, field, ErrorCodes.DUPLICATE_RECORDED_AT,
                        "another measurement of the batch has the same recordedAt"));
            }
        }
        if (!violations.isEmpty()) {
            throw new ValidationException(violations);
        }
    }

    public record DeviceMeasurements(UUID deviceId, List<Measurement> measurements) {
    }
}
