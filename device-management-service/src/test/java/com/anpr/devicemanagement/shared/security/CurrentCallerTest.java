package com.anpr.devicemanagement.shared.security;

import com.anpr.devicemanagement.shared.error.ForbiddenException;
import com.anpr.devicemanagement.shared.error.UnauthorizedException;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class CurrentCallerTest {

    private static final UUID ID = UUID.fromString("7d3f2c1e-0000-4000-8000-000000000000");

    @Test
    void userHeadersGiveAPerson() {
        Caller caller = callerWith("user", ID.toString());

        assertThat(caller).isEqualTo(new Caller.UserCaller(ID));
        assertThat(caller.asUser().accountId()).isEqualTo(ID);
    }

    @Test
    void deviceHeadersGiveADevice() {
        Caller caller = callerWith("device", ID.toString());

        assertThat(caller.asDevice().deviceId()).isEqualTo(ID);
    }

    @Test
    void iamHeadersGiveAnAdministratorIdentifiedByArn() {
        String arn = "arn:aws:sts::000000000000:assumed-role/Admin/someone";

        assertThat(callerWith("iam", arn).asAdministrator().principalArn()).isEqualTo(arn);
    }

    @Test
    void missingOrUnknownHeadersAreUnauthenticated() {
        assertThatThrownBy(() -> callerWith(null, ID.toString())).isInstanceOf(UnauthorizedException.class);
        assertThatThrownBy(() -> callerWith("user", null)).isInstanceOf(UnauthorizedException.class);
        assertThatThrownBy(() -> callerWith("robot", ID.toString())).isInstanceOf(UnauthorizedException.class);
        assertThatThrownBy(() -> callerWith("device", "not-a-uuid")).isInstanceOf(UnauthorizedException.class);
    }

    @Test
    void aCallerOfAnotherKindIsForbidden() {
        Caller device = new Caller.DeviceCaller(ID);

        assertThatThrownBy(device::asUser).isInstanceOf(ForbiddenException.class);
        assertThatThrownBy(device::asAdministrator).isInstanceOf(ForbiddenException.class);
        assertThatThrownBy(() -> new Caller.UserCaller(ID).asDevice()).isInstanceOf(ForbiddenException.class);
    }

    private static Caller callerWith(String type, String id) {
        MockHttpServletRequest request = new MockHttpServletRequest();
        if (type != null) {
            request.addHeader(CurrentCaller.ACCOUNT_TYPE_HEADER, type);
        }
        if (id != null) {
            request.addHeader(CurrentCaller.ACCOUNT_ID_HEADER, id);
        }
        return new CurrentCaller(request).get();
    }
}
