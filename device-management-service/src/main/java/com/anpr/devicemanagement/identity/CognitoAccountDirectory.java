package com.anpr.devicemanagement.identity;

import com.anpr.devicemanagement.config.AwsProperties;
import com.anpr.devicemanagement.internal.provisioning.AccountDirectory;
import com.anpr.devicemanagement.shared.error.ConflictException;
import com.anpr.devicemanagement.shared.error.ErrorCodes;
import com.anpr.devicemanagement.shared.error.FieldViolation;
import com.anpr.devicemanagement.shared.error.TechnicalException;
import com.anpr.devicemanagement.shared.error.ValidationException;
import lombok.extern.slf4j.Slf4j;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Component;
import software.amazon.awssdk.services.cognitoidentityprovider.CognitoIdentityProviderClient;
import software.amazon.awssdk.services.cognitoidentityprovider.model.AdminAddUserToGroupRequest;
import software.amazon.awssdk.services.cognitoidentityprovider.model.AdminCreateUserRequest;
import software.amazon.awssdk.services.cognitoidentityprovider.model.AdminDeleteUserRequest;
import software.amazon.awssdk.services.cognitoidentityprovider.model.AdminListGroupsForUserRequest;
import software.amazon.awssdk.services.cognitoidentityprovider.model.AdminSetUserPasswordRequest;
import software.amazon.awssdk.services.cognitoidentityprovider.model.AttributeType;
import software.amazon.awssdk.services.cognitoidentityprovider.model.GroupType;
import software.amazon.awssdk.services.cognitoidentityprovider.model.InvalidPasswordException;
import software.amazon.awssdk.services.cognitoidentityprovider.model.ListUsersRequest;
import software.amazon.awssdk.services.cognitoidentityprovider.model.MessageActionType;
import software.amazon.awssdk.services.cognitoidentityprovider.model.UserNotFoundException;
import software.amazon.awssdk.services.cognitoidentityprovider.model.UserType;
import software.amazon.awssdk.services.cognitoidentityprovider.model.UsernameExistsException;

import java.util.Optional;
import java.util.UUID;

/**
 * The user pool of people and devices. People are found by their sub (the account id), devices are managed by their
 * username. A device account is created with a permanent password and without any message to send.
 */
@Slf4j
@Component
@Profile("!local")
public class CognitoAccountDirectory implements AccountDirectory {
    private static final String SUB = "sub";

    private final CognitoIdentityProviderClient cognito;
    private final String userPoolId;
    private final String usersGroup;
    private final String devicesGroup;

    public CognitoAccountDirectory(CognitoIdentityProviderClient cognito, AwsProperties aws) {
        this.cognito = cognito;
        this.userPoolId = aws.cognito().userPoolId();
        this.usersGroup = aws.cognito().usersGroup();
        this.devicesGroup = aws.cognito().devicesGroup();
    }

    /** Every account is in exactly one group, so the first page of its groups is all of them. */
    @Override
    public boolean isPerson(UUID accountId) {
        return findUsernameBySub(accountId)
                .map(username -> cognito.adminListGroupsForUser(AdminListGroupsForUserRequest.builder()
                                .userPoolId(userPoolId)
                                .username(username)
                                .build())
                        .groups().stream()
                        .map(GroupType::groupName)
                        .anyMatch(usersGroup::equals))
                .orElse(false);
    }

    @Override
    public UUID createDevice(String username, String password) {
        UserType user;
        try {
            user = cognito.adminCreateUser(AdminCreateUserRequest.builder()
                    .userPoolId(userPoolId)
                    .username(username)
                    .messageAction(MessageActionType.SUPPRESS)
                    .build()).user();
        } catch (UsernameExistsException e) {
            throw new ConflictException(ErrorCodes.USERNAME_TAKEN, "Username is already taken");
        }

        try {
            cognito.adminSetUserPassword(AdminSetUserPasswordRequest.builder()
                    .userPoolId(userPoolId)
                    .username(username)
                    .password(password)
                    .permanent(true)
                    .build());
            cognito.adminAddUserToGroup(AdminAddUserToGroupRequest.builder()
                    .userPoolId(userPoolId)
                    .username(username)
                    .groupName(devicesGroup)
                    .build());
            return sub(user);
        } catch (RuntimeException e) {
            deleteHalfCreated(username, e);
            if (e instanceof InvalidPasswordException) {
                throw ValidationException.of(new FieldViolation(null, "password", ErrorCodes.PASSWORD_POLICY,
                        "does not meet the password policy of the user pool"));
            }
            throw e;
        }
    }

    @Override
    public void deleteDevice(String username) {
        try {
            cognito.adminDeleteUser(AdminDeleteUserRequest.builder()
                    .userPoolId(userPoolId)
                    .username(username)
                    .build());
        } catch (UserNotFoundException e) {
            log.atDebug().addKeyValue("username", username).log("Cognito user already deleted");
        }
    }

    /** The sub is unique and immutable, but it is not the username, so the user is found with a filter. */
    private Optional<String> findUsernameBySub(UUID accountId) {
        return cognito.listUsers(ListUsersRequest.builder()
                        .userPoolId(userPoolId)
                        .filter(SUB + " = \"" + accountId + "\"")
                        .limit(1)
                        .build())
                .users().stream()
                .findFirst()
                .map(UserType::username);
    }

    private void deleteHalfCreated(String username, RuntimeException cause) {
        try {
            deleteDevice(username);
        } catch (RuntimeException deleteFailure) {
            cause.addSuppressed(deleteFailure);
            log.atError().setCause(deleteFailure).addKeyValue("username", username)
                    .log("Half-created Cognito user left behind; delete it in the user pool");
        }
    }

    private static UUID sub(UserType user) {
        return user.attributes().stream()
                .filter(attribute -> SUB.equals(attribute.name()))
                .map(AttributeType::value)
                .map(UUID::fromString)
                .findFirst()
                .orElseThrow(() -> new TechnicalException("Cognito returned a user without sub"));
    }
}
