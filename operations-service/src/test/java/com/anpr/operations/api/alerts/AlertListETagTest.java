package com.anpr.operations.api.alerts;

import com.anpr.operations.internal.alerts.model.Alert;
import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class AlertListETagTest {
    private static final UUID FIRST = UUID.fromString("00000000-0000-4000-8000-000000000001");
    private static final UUID SECOND = UUID.fromString("00000000-0000-4000-8000-000000000002");

    @Test
    void isAWeakETag() {
        assertThat(AlertListETag.of(List.of(alert(FIRST, 0)))).matches("W/\"[0-9a-f]{32}\"");
    }

    @Test
    void theSameAlertsInAnyOrderGiveTheSameETag() {
        assertThat(AlertListETag.of(List.of(alert(FIRST, 0), alert(SECOND, 3))))
                .isEqualTo(AlertListETag.of(List.of(alert(SECOND, 3), alert(FIRST, 0))));
    }

    @Test
    void anUpdatedAlertChangesTheETag() {
        assertThat(AlertListETag.of(List.of(alert(FIRST, 1))))
                .isNotEqualTo(AlertListETag.of(List.of(alert(FIRST, 0))));
    }

    @Test
    void anAddedOrDeletedAlertChangesTheETag() {
        assertThat(AlertListETag.of(List.of(alert(FIRST, 0), alert(SECOND, 0))))
                .isNotEqualTo(AlertListETag.of(List.of(alert(FIRST, 0))));
    }

    private static Alert alert(UUID alertId, long version) {
        // Alert has no setter for the version (JPA raises it), so a stub stands in for a stored alert.
        Alert alert = mock(Alert.class);
        when(alert.getAlertId()).thenReturn(alertId);
        when(alert.getVersion()).thenReturn(version);
        return alert;
    }
}