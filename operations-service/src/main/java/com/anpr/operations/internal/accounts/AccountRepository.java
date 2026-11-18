package com.anpr.operations.internal.accounts;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;

import java.util.UUID;

public interface AccountRepository extends JpaRepository<Account, UUID> {

    /** One statement instead of read-then-insert, so two concurrent callers cannot both insert the account. */
    @Modifying
    @Query(value = "INSERT INTO accounts (account_id) VALUES (:accountId) ON CONFLICT DO NOTHING", nativeQuery = true)
    void insertIfAbsent(UUID accountId);
}
