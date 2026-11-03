package com.anpr.devicemanagement.identity;

import com.anpr.devicemanagement.config.AwsProperties;
import com.anpr.devicemanagement.shared.error.ConflictException;
import com.anpr.devicemanagement.shared.error.ErrorCodes;
import com.anpr.devicemanagement.shared.error.ValidationException;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import software.amazon.awssdk.services.cognitoidentityprovider.CognitoIdentityProviderClient;
import software.amazon.awssdk.services.cognitoidentityprovider.model.AdminAddUserToGroupRequest;
import software.amazon.awssdk.services.cognitoidentityprovider.model.AdminCreateUserRequest;
import software.amazon.awssdk.services.cognitoidentityprovider.model.AdminCreateUserResponse;
import software.amazon.awssdk.services.cognitoidentityprovider.model.AdminDeleteUserRequest;
import software.amazon.awssdk.services.cognitoidentityprovider.model.AdminListGroupsForUserRequest;
import software.amazon.awssdk.services.cognitoidentityprovider.model.AdminListGroupsForUserResponse;
import software.amazon.awssdk.services.cognitoidentityprovider.model.AdminSetUserPasswordRequest;
import software.amazon.awssdk.services.cognitoidentityprovider.model.AttributeType;
import software.amazon.awssdk.services.cognitoidentityprovider.model.GroupType;
import software.amazon.awssdk.services.cognitoidentityprovider.model.InvalidPasswordException;
import software.amazon.awssdk.services.cognitoidentityprovider.model.ListUsersRequest;
import software.amazon.awssdk.services.cognitoidentityprovider.model.ListUsersResponse;
import software.amazon.awssdk.services.cognitoidentityprovider.model.MessageActionType;
import software.amazon.awssdk.services.cognitoidentityprovider.model.UserNotFoundException;
import software.amazon.awssdk.services.cognitoidentityprovider.model.UserType;
import software.amazon.awssdk.services.cognitoidentityprovider.model.UsernameExistsException;

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class CognitoAccountDirectoryTest {

    private static final String POOL = "eu-central-1_test";
    private static final UUID SUB = UUID.fromString("7d3f2c1e-0000-4000-8000-000000000000");

    @Mock
    private CognitoIdentityProviderClient cognito;

    private CognitoAccountDirectory directory;

    @BeforeEach
    void setUp() {
        AwsProperties aws = new AwsProperties("eu-central-1", null, null,
                new AwsProperties.Cognito(POOL, "users", "devices"), null);
        directory = new CognitoAccountDirectory(cognito, aws);
    }

    @Test
    void aPersonIsAUserFoundBySubInTheGroupOfUsers() {
        givenUserWithGroup("alice", "users");

        assertThat(directory.isPerson(SUB)).isTrue();

        ArgumentCaptor<ListUsersRequest> request = ArgumentCaptor.forClass(ListUsersRequest.class);
        verify(cognito).listUsers(request.capture());
        assertThat(request.getValue().filter()).isEqualTo("sub = \"" + SUB + "\"");
    }

    @Test
    void aDeviceAccountIsNotAPerson() {
        givenUserWithGroup("rpi-01", "devices");

        assertThat(directory.isPerson(SUB)).isFalse();
    }

    @Test
    void anUnknownSubIsNotAPerson() {
        when(cognito.listUsers(any(ListUsersRequest.class))).thenReturn(ListUsersResponse.builder().build());

        assertThat(directory.isPerson(SUB)).isFalse();
    }

    @Test
    void createsTheDeviceSilentlyWithAPermanentPasswordInTheGroupOfDevices() {
        givenCreatedUser();

        assertThat(directory.createDevice("rpi-01", "Secret-password-1")).isEqualTo(SUB);

        ArgumentCaptor<AdminCreateUserRequest> create = ArgumentCaptor.forClass(AdminCreateUserRequest.class);
        verify(cognito).adminCreateUser(create.capture());
        assertThat(create.getValue().messageAction()).isEqualTo(MessageActionType.SUPPRESS);
        ArgumentCaptor<AdminSetUserPasswordRequest> password = ArgumentCaptor.forClass(AdminSetUserPasswordRequest.class);
        verify(cognito).adminSetUserPassword(password.capture());
        assertThat(password.getValue().permanent()).isTrue();
        ArgumentCaptor<AdminAddUserToGroupRequest> group = ArgumentCaptor.forClass(AdminAddUserToGroupRequest.class);
        verify(cognito).adminAddUserToGroup(group.capture());
        assertThat(group.getValue().groupName()).isEqualTo("devices");
    }

    @Test
    void aTakenUsernameIsAConflict() {
        when(cognito.adminCreateUser(any(AdminCreateUserRequest.class)))
                .thenThrow(UsernameExistsException.builder().message("exists").build());

        assertThatThrownBy(() -> directory.createDevice("rpi-01", "Secret-password-1"))
                .isInstanceOf(ConflictException.class)
                .hasFieldOrPropertyWithValue("code", ErrorCodes.USERNAME_TAKEN);
        verify(cognito, never()).adminDeleteUser(any(AdminDeleteUserRequest.class));
    }

    @Test
    void aWeakPasswordIsAValidationErrorAndLeavesNoUserBehind() {
        givenCreatedUser();
        when(cognito.adminSetUserPassword(any(AdminSetUserPasswordRequest.class)))
                .thenThrow(InvalidPasswordException.builder().message("weak").build());

        assertThatThrownBy(() -> directory.createDevice("rpi-01", "weak-password"))
                .isInstanceOf(ValidationException.class)
                .satisfies(e -> assertThat(((ValidationException) e).getViolations().getFirst().code())
                        .isEqualTo(ErrorCodes.PASSWORD_POLICY));
        verify(cognito).adminDeleteUser(AdminDeleteUserRequest.builder().userPoolId(POOL).username("rpi-01").build());
    }

    @Test
    void deletingAMissingUserIsNotAnError() {
        when(cognito.adminDeleteUser(any(AdminDeleteUserRequest.class)))
                .thenThrow(UserNotFoundException.builder().message("gone").build());

        assertThatCode(() -> directory.deleteDevice("rpi-01")).doesNotThrowAnyException();
    }

    private void givenUserWithGroup(String username, String group) {
        when(cognito.listUsers(any(ListUsersRequest.class)))
                .thenReturn(ListUsersResponse.builder().users(UserType.builder().username(username).build()).build());
        when(cognito.adminListGroupsForUser(any(AdminListGroupsForUserRequest.class)))
                .thenReturn(AdminListGroupsForUserResponse.builder()
                        .groups(GroupType.builder().groupName(group).build())
                        .build());
    }

    private void givenCreatedUser() {
        when(cognito.adminCreateUser(any(AdminCreateUserRequest.class)))
                .thenReturn(AdminCreateUserResponse.builder()
                        .user(UserType.builder()
                                .username("rpi-01")
                                .attributes(AttributeType.builder().name("sub").value(SUB.toString()).build())
                                .build())
                        .build());
    }
}
