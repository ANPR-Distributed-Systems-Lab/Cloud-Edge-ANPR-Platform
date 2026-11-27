package com.anpr.operations.internal.accounts;

import com.anpr.operations.internal.accounts.repository.AccountRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.UUID;

/** Accounts known to this service. Other areas create them only through this class. */
@Service
@RequiredArgsConstructor
public class AccountService {
    private final AccountRepository accountRepository;

    /** Idempotent: a second call for the same account does nothing. */
    @Transactional
    public void ensureExists(UUID accountId) {
        accountRepository.insertIfAbsent(accountId);
    }
}
