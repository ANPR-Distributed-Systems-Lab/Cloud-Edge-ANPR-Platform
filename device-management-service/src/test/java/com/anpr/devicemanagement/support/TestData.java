package com.anpr.devicemanagement.support;

import com.anpr.devicemanagement.internal.configuration.DeviceSettings;
import com.anpr.devicemanagement.internal.metrics.Measurement;

import java.time.Instant;

/** Valid domain objects for tests; each call returns new instances. */
public final class TestData {

    private TestData() {
    }

    public static DeviceSettings settings(int metricsSeconds) {
        DeviceSettings.Batching batching = new DeviceSettings.Batching();
        batching.setDetectionsBatchSize(20);
        batching.setLocationsBatchSize(100);
        batching.setImageUrlsBatchSize(20);
        batching.setMaxBatchDelaySeconds(10);

        DeviceSettings.Ml ml = new DeviceSettings.Ml();
        ml.setDetectorMinConfidence(0.5);
        ml.setOcrMinConfidence(0.6);
        ml.setReadableMinProbability(0.8);
        ml.setMinPlateWidthPx(60);
        ml.setMinEdgeMarginPx(10);

        DeviceSettings.Models models = new DeviceSettings.Models();
        models.setDetector("v2");
        models.setOcr("v3");

        DeviceSettings.Intervals intervals = new DeviceSettings.Intervals();
        intervals.setMetricsSeconds(metricsSeconds);
        intervals.setConfigPollSeconds(60);
        intervals.setAlertsPollSeconds(60);
        intervals.setLocationSampleSeconds(5);

        DeviceSettings.Exposure exposure = new DeviceSettings.Exposure();
        exposure.setMode(DeviceSettings.ExposureMode.MANUAL);
        exposure.setExposureUs(2000);
        exposure.setGain(4.0);
        exposure.setMaxExposureUs(4000);
        exposure.setMaxGain(12.0);
        exposure.setTargetBrightness(0.4);

        DeviceSettings.WhiteBalance whiteBalance = new DeviceSettings.WhiteBalance();
        whiteBalance.setMode(DeviceSettings.WhiteBalanceMode.DAYLIGHT);
        whiteBalance.setRedGain(2.0);
        whiteBalance.setBlueGain(1.6);

        DeviceSettings.Camera camera = new DeviceSettings.Camera();
        camera.setExposure(exposure);
        camera.setWhiteBalance(whiteBalance);
        camera.setFps(2.0);
        camera.setHflip(true);
        camera.setVflip(false);

        DeviceSettings settings = new DeviceSettings();
        settings.setPlateCooldownSeconds(60);
        settings.setBatching(batching);
        settings.setMl(ml);
        settings.setModels(models);
        settings.setIntervals(intervals);
        settings.setCamera(camera);
        return settings;
    }

    public static Measurement measurement(Instant recordedAt) {
        Measurement.QueueLengths queues = new Measurement.QueueLengths();
        queues.setDetectionsPending(3);
        queues.setLocationsPending(10);
        queues.setImagesPending(1);

        Measurement.GpsStatus gps = new Measurement.GpsStatus();
        gps.setFix(Measurement.GpsFix.FIX_3D);
        gps.setSatellites(9);

        Measurement measurement = new Measurement();
        measurement.setRecordedAt(recordedAt);
        measurement.setCpuTemperatureC(61.5);
        measurement.setCpuUsagePercent(42.0);
        measurement.setRamUsagePercent(55.0);
        measurement.setProcessingFps(2.0);
        measurement.setQueues(queues);
        measurement.setDiskFreeMb(12_000L);
        measurement.setUptimeSeconds(3_600L);
        measurement.setGps(gps);
        return measurement;
    }
}
