package com.anpr.operations.internal.accounts;

import com.anpr.operations.internal.accounts.repository.AccountRepository;
import org.junit.jupiter.api.Test;

import java.util.UUID;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;

class AccountServiceTest {
    private final AccountRepository accountRepository = mock(AccountRepository.class);
    private final AccountService accountService = new AccountService(accountRepository);

    @Test
    void ensureExistsInsertsTheAccountOnlyWhenAbsent() {
        UUID accountId = UUID.randomUUID();

        accountService.ensureExists(accountId);

        verify(accountRepository).insertIfAbsent(accountId);
    }
}
