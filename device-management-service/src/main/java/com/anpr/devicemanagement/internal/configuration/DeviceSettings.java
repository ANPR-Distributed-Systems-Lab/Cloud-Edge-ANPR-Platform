package com.anpr.devicemanagement.internal.configuration;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import lombok.Getter;
import lombok.Setter;
import software.amazon.awssdk.enhanced.dynamodb.mapper.annotations.DynamoDbBean;

/**
 * Operating parameters of a device (View 4), stored in its configuration item and read by the device when it polls.
 * <p>
 * The allowed ranges are defined by the contract (device-management-api.yaml) and checked when a person saves the
 * configuration. The constraints below only make the defaults of the service (application.yaml) complete: a missing
 * default fails the startup. The classes are mutable JavaBeans because both the DynamoDB mapper and the
 * configuration binder require it.
 */
@DynamoDbBean
@Getter
@Setter
public class DeviceSettings {

    /** After a plate is sent, the same plate is not sent again for this many seconds. */
    @NotNull
    private Integer plateCooldownSeconds;

    @Valid
    @NotNull
    private Batching batching;

    @Valid
    @NotNull
    private Ml ml;

    @Valid
    @NotNull
    private Models models;

    @Valid
    @NotNull
    private Intervals intervals;

    @Valid
    @NotNull
    private Camera camera;

    /** How the device groups its local queues before sending them. */
    @DynamoDbBean
    @Getter
    @Setter
    public static class Batching {
        @NotNull
        private Integer detectionsBatchSize;
        @NotNull
        private Integer locationsBatchSize;
        @NotNull
        private Integer imageUrlsBatchSize;
        @NotNull
        private Integer maxBatchDelaySeconds;
    }

    /** The send rule of the device: which detections it reads and sends. */
    @DynamoDbBean
    @Getter
    @Setter
    public static class Ml {
        @NotNull
        private Double detectorMinConfidence;
        @NotNull
        private Double ocrMinConfidence;
        @NotNull
        private Double readableMinProbability;
        @NotNull
        private Integer minPlateWidthPx;
        @NotNull
        private Integer minEdgeMarginPx;
    }

    /** The published model versions the device runs (internal/models). */
    @DynamoDbBean
    @Getter
    @Setter
    public static class Models {
        @NotNull
        private String detector;
        @NotNull
        private String ocr;
    }

    @DynamoDbBean
    @Getter
    @Setter
    public static class Intervals {
        @NotNull
        private Integer metricsSeconds;
        @NotNull
        private Integer configPollSeconds;
        @NotNull
        private Integer alertsPollSeconds;
        @NotNull
        private Integer locationSampleSeconds;
    }

    /** Capture settings; the resolution is fixed (4056x3040). */
    @DynamoDbBean
    @Getter
    @Setter
    public static class Camera {
        @Valid
        @NotNull
        private Exposure exposure;
        @Valid
        @NotNull
        private WhiteBalance whiteBalance;
        @NotNull
        private Double fps;
        /** How the camera is mounted: the image is flipped back before it reaches the models. */
        @NotNull
        private Boolean hflip;
        @NotNull
        private Boolean vflip;
    }

    @DynamoDbBean
    @Getter
    @Setter
    public static class Exposure {
        @NotNull
        private ExposureMode mode;
        @NotNull
        private Integer exposureUs;
        @NotNull
        private Double gain;
        @NotNull
        private Integer maxExposureUs;
        @NotNull
        private Double maxGain;
        @NotNull
        private Double targetBrightness;
    }

    @DynamoDbBean
    @Getter
    @Setter
    public static class WhiteBalance {
        @NotNull
        private WhiteBalanceMode mode;
        @NotNull
        private Double redGain;
        @NotNull
        private Double blueGain;
    }

    /** The modes of the software auto exposure on the device (rpi-edge/common/autoexposure.py). */
    public enum ExposureMode {
        MANUAL, AUTO, AUTO_GAIN, AUTO_EXPOSURE
    }

    public enum WhiteBalanceMode {
        AUTO, DAYLIGHT, CLOUDY, TUNGSTEN, FLUORESCENT, INDOOR, MANUAL
    }
}
