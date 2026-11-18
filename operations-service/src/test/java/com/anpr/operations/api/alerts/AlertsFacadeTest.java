package com.anpr.operations.api.alerts;

import com.anpr.operations.api.generated.model.AlertPage;
import com.anpr.operations.api.generated.model.AlertSortField;
import com.anpr.operations.api.generated.model.SortDirection;
import com.anpr.operations.internal.alerts.AlertService;
import com.anpr.operations.internal.alerts.model.Alert;
import com.anpr.operations.internal.alerts.repository.AlertVersion;
import com.anpr.operations.shared.security.CurrentAccount;
import org.junit.jupiter.api.Test;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;

import java.util.List;
import java.util.Map;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class AlertsFacadeTest {
    private static final UUID FIRST = UUID.fromString("00000000-0000-4000-8000-000000000001");
    private static final UUID SECOND = UUID.fromString("00000000-0000-4000-8000-000000000002");

    private final AlertService alertService = mock(AlertService.class);
    private final AlertApiMapper mapper = mock(AlertApiMapper.class);
    private final CurrentAccount currentAccount = mock(CurrentAccount.class);
    private final AlertsFacade facade = new AlertsFacade(alertService, mapper, currentAccount);

    @Test
    void deviceThatHasTheCurrentListGets304AndTheAlertsAreNotLoaded() {
        List<AlertVersion> versions = List.of(version(FIRST, 0));
        when(currentAccount.isDevice()).thenReturn(true);
        when(alertService.versionsForDevice()).thenReturn(versions);
        String current = AlertsFacade.eTagOf(Map.of(FIRST, 0L));

        ResponseEntity<AlertPage> response = list(current);

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.NOT_MODIFIED);
        assertThat(response.getHeaders().getETag()).isEqualTo(current);
        assertThat(response.getBody()).isNull();
        verify(alertService, never()).listForDevice();
    }

    @Test
    void deviceWithAnOutdatedListGetsTheWholeListWithAnETag() {
        Alert alert = alert(FIRST, 1);
        List<AlertVersion> versions = List.of(version(FIRST, 1));
        AlertPage body = new AlertPage();
        when(currentAccount.isDevice()).thenReturn(true);
        when(alertService.versionsForDevice()).thenReturn(versions);
        when(alertService.listForDevice()).thenReturn(List.of(alert));
        when(mapper.toDevicePage(List.of(alert))).thenReturn(body);

        ResponseEntity<AlertPage> response = list(AlertsFacade.eTagOf(Map.of(FIRST, 0L)));

        assertThat(response.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(response.getBody()).isSameAs(body);
        assertThat(response.getHeaders().getETag()).isEqualTo(AlertsFacade.eTagOf(Map.of(FIRST, 1L)));
    }

    @Test
    @SuppressWarnings("unchecked")
    void personGetsOnePageWithoutAnETag() {
        when(currentAccount.isDevice()).thenReturn(false);
        Page<Alert> page = mock(Page.class);
        when(alertService.list(any(), any(Pageable.class))).thenReturn(page);
        when(mapper.toPage(page)).thenReturn(new AlertPage());

        ResponseEntity<AlertPage> response = list(null);

        assertThat(response.getHeaders().getETag()).isNull();
        verify(alertService, never()).versionsForDevice();
        verify(alertService, never()).listForDevice();
    }

    @Test
    void eTagIsWeak() {
        assertThat(AlertsFacade.eTagOf(Map.of(FIRST, 0L))).matches("W/\"[0-9a-f]{32}\"");
    }

    @Test
    void anUpdatedAlertChangesTheETag() {
        assertThat(AlertsFacade.eTagOf(Map.of(FIRST, 1L))).isNotEqualTo(AlertsFacade.eTagOf(Map.of(FIRST, 0L)));
    }

    @Test
    void anAddedOrDeletedAlertChangesTheETag() {
        assertThat(AlertsFacade.eTagOf(Map.of(FIRST, 0L, SECOND, 0L)))
                .isNotEqualTo(AlertsFacade.eTagOf(Map.of(FIRST, 0L)));
    }

    @Test
    void ifNoneMatchAcceptsAnyOfSeveralTagsTheWildcardAndTheStrongForm() {
        String eTag = AlertsFacade.eTagOf(Map.of(FIRST, 0L));

        assertThat(AlertsFacade.matches("W/\"other\", " + eTag, eTag)).isTrue();
        assertThat(AlertsFacade.matches("*", eTag)).isTrue();
        assertThat(AlertsFacade.matches(eTag.substring(2), eTag)).isTrue();
        assertThat(AlertsFacade.matches("W/\"other\"", eTag)).isFalse();
        assertThat(AlertsFacade.matches(null, eTag)).isFalse();
    }

    private ResponseEntity<AlertPage> list(String ifNoneMatch) {
        return facade.list(0, 20, AlertSortField.CREATED_AT, SortDirection.DESC, null, null, null, ifNoneMatch);
    }

    private static AlertVersion version(UUID alertId, long version) {
        AlertVersion row = mock(AlertVersion.class);
        when(row.getAlertId()).thenReturn(alertId);
        when(row.getVersion()).thenReturn(version);
        return row;
    }

    private static Alert alert(UUID alertId, long version) {
        // Alert has no setter for the version (JPA raises it), so a stub stands in for a stored alert.
        Alert alert = mock(Alert.class);
        when(alert.getAlertId()).thenReturn(alertId);
        when(alert.getVersion()).thenReturn(version);
        return alert;
    }
}
