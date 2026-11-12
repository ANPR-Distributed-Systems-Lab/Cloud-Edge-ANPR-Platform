package com.anpr.operations.internal.livefeed;

import com.anpr.operations.shared.error.BadRequestException;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

import java.nio.charset.StandardCharsets;
import java.time.OffsetDateTime;
import java.util.Base64;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class LiveFeedCursorTest {

    @Test
    void decodingAnEncodedCursorGivesTheSameStoringTimeToTheMicrosecondAndTheSameId() {
        LiveFeedCursor cursor = new LiveFeedCursor(OffsetDateTime.parse("2026-10-30T09:19:00.123456Z"), UUID.randomUUID());

        LiveFeedCursor decoded = LiveFeedCursor.decode(cursor.encode());

        assertThat(decoded.storedAt().toInstant()).isEqualTo(cursor.storedAt().toInstant());
        assertThat(decoded.detectionId()).isEqualTo(cursor.detectionId());
    }

    @ParameterizedTest
    @ValueSource(strings = {"", "not base64!", "MTIz", "MTIzOm5vdC1hLXV1aWQ", "YWJjOjVlMWMwMDAwLTAwMDAtNDAwMC04MDAwLTAwMDAwMDAwMDAxMw"})
    void aCursorThatIsNotOursIsRejected(String cursor) {
        assertThatThrownBy(() -> LiveFeedCursor.decode(cursor)).isInstanceOf(BadRequestException.class);
    }

    @Test
    void theEncodedFormIsUrlSafe() {
        String encoded = new LiveFeedCursor(OffsetDateTime.parse("2026-10-30T09:19:00Z"), UUID.randomUUID()).encode();

        assertThat(encoded).matches("[A-Za-z0-9_-]+");
        assertThat(new String(Base64.getUrlDecoder().decode(encoded), StandardCharsets.UTF_8)).contains(":");
    }
}
