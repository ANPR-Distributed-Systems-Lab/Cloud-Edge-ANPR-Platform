package com.anpr.operations.internal.alerts;

import com.anpr.operations.shared.error.ConflictException;
import com.anpr.operations.shared.error.ErrorCodes;
import com.anpr.operations.shared.error.NotFoundException;
import com.anpr.operations.shared.security.CurrentAccount;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageImpl;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.test.util.ReflectionTestUtils;

import java.time.Clock;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.lenient;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class AlertServiceTest {

    private static final UUID ACCOUNT_ID = UUID.fromString("11111111-1111-1111-1111-111111111111");
    private static final Instant NOW = Instant.parse("2026-10-27T10:00:00Z");

    @Mock
    private AlertRepository alertRepository;

    @Mock
    private CurrentAccount currentAccount;

    private AlertService alertService;

    @BeforeEach
    void setUp() {
        Clock clock = Clock.fixed(NOW, ZoneOffset.UTC);
        alertService = new AlertService(alertRepository, currentAccount, clock);
        lenient().when(currentAccount.id()).thenReturn(ACCOUNT_ID);
    }

    @Test
    void createSavesAlertForCurrentAccount() {
        when(alertRepository.existsByAccountIdAndPlate(ACCOUNT_ID, "WA12345")).thenReturn(false);
        when(alertRepository.save(any(Alert.class))).thenAnswer(invocation -> invocation.getArgument(0));

        Alert created = alertService.create("WA12345", "Stolen");

        assertThat(created.getAccountId()).isEqualTo(ACCOUNT_ID);
        assertThat(created.getPlate()).isEqualTo("WA12345");
        assertThat(created.getCreatedAt()).isEqualTo(OffsetDateTime.ofInstant(NOW, ZoneOffset.UTC));
    }

    @Test
    void createWithDuplicatePlateThrowsConflict() {
        when(alertRepository.existsByAccountIdAndPlate(ACCOUNT_ID, "WA12345")).thenReturn(true);

        assertThatThrownBy(() -> alertService.create("WA12345", null))
                .isInstanceOfSatisfying(ConflictException.class,
                        e -> assertThat(e.getCode()).isEqualTo(ErrorCodes.ALERT_ALREADY_EXISTS));
        verify(alertRepository, never()).save(any());
    }

    @Test
    void getMissingAlertThrowsNotFound() {
        UUID alertId = UUID.randomUUID();
        when(alertRepository.findByAlertIdAndAccountId(alertId, ACCOUNT_ID)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> alertService.get(alertId))
                .isInstanceOfSatisfying(NotFoundException.class,
                        e -> assertThat(e.getCode()).isEqualTo(ErrorCodes.ALERT_NOT_FOUND));
    }

    @Test
    void listQueriesCurrentAccount() {
        Pageable pageable = PageRequest.of(0, 20);
        Page<Alert> page = new PageImpl<>(List.of(existingAlert("WA12345", 0L)));
        when(alertRepository.findByAccountId(ACCOUNT_ID, pageable)).thenReturn(page);

        assertThat(alertService.list(pageable)).isSameAs(page);
    }

    @Test
    void updateWithStaleVersionThrowsConflict() {
        Alert alert = existingAlert("WA12345", 1L);
        when(alertRepository.findByAlertIdAndAccountId(alert.getAlertId(), ACCOUNT_ID)).thenReturn(Optional.of(alert));

        assertThatThrownBy(() -> alertService.update(alert.getAlertId(), "WA12345", null, 0L))
                .isInstanceOfSatisfying(ConflictException.class,
                        e -> assertThat(e.getCode()).isEqualTo(ErrorCodes.CONCURRENT_MODIFICATION));
        verify(alertRepository, never()).saveAndFlush(any());
    }

    @Test
    void updateToPlateUsedByAnotherAlertThrowsConflict() {
        Alert alert = existingAlert("WA12345", 0L);
        when(alertRepository.findByAlertIdAndAccountId(alert.getAlertId(), ACCOUNT_ID)).thenReturn(Optional.of(alert));
        when(alertRepository.existsByAccountIdAndPlate(ACCOUNT_ID, "KR99999")).thenReturn(true);

        assertThatThrownBy(() -> alertService.update(alert.getAlertId(), "KR99999", null, 0L))
                .isInstanceOfSatisfying(ConflictException.class,
                        e -> assertThat(e.getCode()).isEqualTo(ErrorCodes.ALERT_ALREADY_EXISTS));
        verify(alertRepository, never()).saveAndFlush(any());
    }

    @Test
    void updateToFreePlateSavesChanges() {
        Alert alert = existingAlert("WA12345", 0L);
        when(alertRepository.findByAlertIdAndAccountId(alert.getAlertId(), ACCOUNT_ID)).thenReturn(Optional.of(alert));
        when(alertRepository.existsByAccountIdAndPlate(ACCOUNT_ID, "KR99999")).thenReturn(false);
        when(alertRepository.saveAndFlush(alert)).thenReturn(alert);

        Alert updated = alertService.update(alert.getAlertId(), "KR99999", "Moved", 0L);

        assertThat(updated.getPlate()).isEqualTo("KR99999");
        assertThat(updated.getAlertText()).isEqualTo("Moved");
    }

    @Test
    void updateKeepingSamePlateSkipsDuplicateCheck() {
        Alert alert = existingAlert("WA12345", 0L);
        when(alertRepository.findByAlertIdAndAccountId(alert.getAlertId(), ACCOUNT_ID)).thenReturn(Optional.of(alert));
        when(alertRepository.saveAndFlush(alert)).thenReturn(alert);

        Alert updated = alertService.update(alert.getAlertId(), "WA12345", "New text", 0L);

        assertThat(updated.getAlertText()).isEqualTo("New text");
        verify(alertRepository, never()).existsByAccountIdAndPlate(any(), anyString());
    }

    @Test
    void deleteRemovesOwnedAlert() {
        Alert alert = existingAlert("WA12345", 0L);
        when(alertRepository.findByAlertIdAndAccountId(alert.getAlertId(), ACCOUNT_ID)).thenReturn(Optional.of(alert));

        alertService.delete(alert.getAlertId());

        verify(alertRepository).delete(alert);
    }

    @Test
    void deleteMissingAlertThrowsNotFound() {
        UUID alertId = UUID.randomUUID();
        when(alertRepository.findByAlertIdAndAccountId(alertId, ACCOUNT_ID)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> alertService.delete(alertId))
                .isInstanceOf(NotFoundException.class);
        verify(alertRepository, never()).delete(any());
    }

    private static Alert existingAlert(String plate, long version) {
        Alert alert = Alert.create(ACCOUNT_ID, plate, null, OffsetDateTime.ofInstant(NOW, ZoneOffset.UTC));
        ReflectionTestUtils.setField(alert, "version", version);
        return alert;
    }
}