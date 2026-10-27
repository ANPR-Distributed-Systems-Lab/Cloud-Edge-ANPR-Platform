package com.anpr.operations.shared.security;

import com.anpr.operations.shared.error.ErrorCodes;
import com.anpr.operations.shared.error.UnauthorizedException;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/**
 * Unit tests: no Spring context, no database. The account id comes only from the
 * header injected by API Gateway.
 */
class CurrentAccountTest {

    @Test
    void returnsTheAccountIdFromTheHeader() {
        UUID accountId = UUID.randomUUID();
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader(CurrentAccount.ACCOUNT_HEADER, accountId.toString());

        assertThat(new CurrentAccount(request).id()).isEqualTo(accountId);
    }

    @Test
    void missingHeaderIsUnauthenticated() {
        CurrentAccount account = new CurrentAccount(new MockHttpServletRequest());

        assertThatThrownBy(account::id)
                .isInstanceOfSatisfying(UnauthorizedException.class,
                        e -> assertThat(e.getCode()).isEqualTo(ErrorCodes.UNAUTHENTICATED));
    }
}
