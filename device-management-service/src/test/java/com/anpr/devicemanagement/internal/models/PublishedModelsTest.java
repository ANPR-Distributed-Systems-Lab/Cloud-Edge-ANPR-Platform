package com.anpr.devicemanagement.internal.models;

import com.anpr.devicemanagement.internal.configuration.DeviceSettings;
import com.anpr.devicemanagement.shared.error.ConflictException;
import com.anpr.devicemanagement.shared.error.ErrorCodes;
import com.anpr.devicemanagement.shared.error.FieldViolation;
import com.anpr.devicemanagement.shared.error.ValidationException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.util.List;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.assertj.core.api.InstanceOfAssertFactories.list;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class PublishedModelsTest {
    private static final ModelRelease DETECTOR_V2 =
            new ModelRelease("detector", "v2", List.of(new ModelRelease.File("model.onnx", "a".repeat(64), 1)));

    @Mock
    private ModelReleases releases;

    private PublishedModels publishedModels;

    @BeforeEach
    void setUp() {
        publishedModels = new PublishedModels(releases);
    }

    @Test
    void publishedVersionsPass() {
        when(releases.find(ModelName.DETECTOR, "v2")).thenReturn(Optional.of(DETECTOR_V2));
        when(releases.find(ModelName.OCR, "v3")).thenReturn(Optional.of(
                new ModelRelease("ocr", "v3", List.of(new ModelRelease.File("model.onnx", "b".repeat(64), 1)))));

        assertThatCode(() -> publishedModels.requirePublished(models("v2", "v3"))).doesNotThrowAnyException();
    }

    @Test
    void everyUnpublishedVersionIsNamed() {
        when(releases.find(ModelName.DETECTOR, "v9")).thenReturn(Optional.empty());
        when(releases.find(ModelName.OCR, "v8")).thenReturn(Optional.empty());

        assertThatThrownBy(() -> publishedModels.requirePublished(models("v9", "v8")))
                .isInstanceOf(ValidationException.class)
                .extracting(e -> ((ValidationException) e).getViolations(), list(FieldViolation.class))
                .extracting(FieldViolation::field, FieldViolation::code)
                .containsExactly(
                        org.assertj.core.groups.Tuple.tuple("models.detector", ErrorCodes.MODEL_NOT_PUBLISHED),
                        org.assertj.core.groups.Tuple.tuple("models.ocr", ErrorCodes.MODEL_NOT_PUBLISHED));
    }

    @Test
    void aReleaseThatIsNotPublishedIsAConflict() {
        when(releases.find(ModelName.DETECTOR, "v2")).thenReturn(Optional.of(DETECTOR_V2));
        when(releases.find(ModelName.OCR, "v4")).thenReturn(Optional.empty());

        assertThat(publishedModels.release(ModelName.DETECTOR, "v2")).isSameAs(DETECTOR_V2);
        assertThatThrownBy(() -> publishedModels.release(ModelName.OCR, "v4"))
                .isInstanceOf(ConflictException.class)
                .hasFieldOrPropertyWithValue("code", ErrorCodes.MODEL_NOT_PUBLISHED);
    }

    private static DeviceSettings.Models models(String detector, String ocr) {
        DeviceSettings.Models models = new DeviceSettings.Models();
        models.setDetector(detector);
        models.setOcr(ocr);
        return models;
    }
}
