package com.anpr.operations.internal.alerts;

import com.anpr.operations.TestcontainersConfiguration;
import com.anpr.operations.internal.alerts.model.Alert;
import com.anpr.operations.internal.alerts.repository.AlertRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.test.context.ActiveProfiles;

import java.io.PrintWriter;
import java.io.StringWriter;
import java.time.OffsetDateTime;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.catchThrowableOfType;

/**
 * A database error must not carry the values of the failing row into exceptions, and so into the logs: the plate is
 * personal data. The name of the violated constraint must stay, AlertService maps it to 409.
 */
@SpringBootTest
@ActiveProfiles("test")
@Import(TestcontainersConfiguration.class)
class DatabaseErrorDetailIT {
    private static final String PLATE = "PO22222";

    @Autowired
    private AlertRepository alertRepository;

    @Test
    void constraintViolationNamesTheConstraintButNotTheValues() {
        UUID account = UUID.randomUUID();
        alertRepository.saveAndFlush(Alert.create(account, PLATE, null, OffsetDateTime.now()));

        DataIntegrityViolationException error = catchThrowableOfType(DataIntegrityViolationException.class,
                () -> alertRepository.saveAndFlush(Alert.create(account, PLATE, null, OffsetDateTime.now())));

        String logged = stackTraceOf(error);
        assertThat(logged).contains("uq_alerts_account_plate");
        assertThat(logged).doesNotContain(PLATE).doesNotContain(account.toString());
    }

    /** What a logger prints for the exception: messages of the whole cause chain. */
    private static String stackTraceOf(Throwable error) {
        StringWriter out = new StringWriter();
        error.printStackTrace(new PrintWriter(out));
        return out.toString();
    }
}
