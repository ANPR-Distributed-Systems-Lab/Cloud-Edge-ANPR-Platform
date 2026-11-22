package com.anpr.operations.shared.tracing;

import jakarta.servlet.ServletRequest;
import jakarta.servlet.ServletResponse;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.mock.web.MockFilterChain;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;

class TraceIdFilterTest {

    private final TraceIdFilter filter = new TraceIdFilter();

    @Test
    void theClientTraceIdWins() throws Exception {
        assertThat(traceIdFor("trace-abc-1", "JZoPFhq3FiAEMbA=")).isEqualTo("trace-abc-1");
    }

    @Test
    void withoutAValidClientTraceIdTheGatewayRequestIdIsUsed() throws Exception {
        assertThat(traceIdFor(null, "JZoPFhq3FiAEMbA=")).isEqualTo("JZoPFhq3FiAEMbA=");
        assertThat(traceIdFor("not valid!", "JZoPFhq3FiAEMbA=")).isEqualTo("JZoPFhq3FiAEMbA=");
    }

    @Test
    void withoutEitherANewOneIsGenerated() throws Exception {
        assertThat(UUID.fromString(traceIdFor(null, null))).isNotNull();
    }

    @Test
    void theTraceIdIsInTheMdcDuringTheRequestAndInTheResponse() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.addHeader(TraceId.HEADER, "trace-abc-1");
        MockHttpServletResponse response = new MockHttpServletResponse();
        AtomicReference<String> duringRequest = new AtomicReference<>();

        filter.doFilter(request, response, new MockFilterChain() {
            @Override
            public void doFilter(ServletRequest req, ServletResponse res) {
                duringRequest.set(MDC.get(TraceId.MDC_KEY));
            }
        });

        assertThat(duringRequest.get()).isEqualTo("trace-abc-1");
        assertThat(response.getHeader(TraceId.HEADER)).isEqualTo("trace-abc-1");
        assertThat(MDC.get(TraceId.MDC_KEY)).isNull();
    }

    @Test
    void withTheClientTraceIdTheGatewayRequestIdIsLoggedToo() throws Exception {
        assertThat(gatewayRequestIdInTheMdcFor("trace-abc-1", "JZoPFhq3FiAEMbA=")).isEqualTo("JZoPFhq3FiAEMbA=");
        assertThat(MDC.get(TraceId.GATEWAY_REQUEST_ID_MDC_KEY)).isNull();
    }

    @Test
    void theGatewayRequestIdIsNotRepeatedWhenItIsTheTraceId() throws Exception {
        assertThat(gatewayRequestIdInTheMdcFor(null, "JZoPFhq3FiAEMbA=")).isNull();
        assertThat(gatewayRequestIdInTheMdcFor("trace-abc-1", null)).isNull();
    }

    /** Reads the MDC from inside the request, where the application code would log. */
    private String gatewayRequestIdInTheMdcFor(String clientTraceId, String gatewayRequestId) throws Exception {
        AtomicReference<String> duringRequest = new AtomicReference<>();
        filter.doFilter(request(clientTraceId, gatewayRequestId), new MockHttpServletResponse(), new MockFilterChain() {
            @Override
            public void doFilter(ServletRequest req, ServletResponse res) {
                duringRequest.set(MDC.get(TraceId.GATEWAY_REQUEST_ID_MDC_KEY));
            }
        });
        return duringRequest.get();
    }

    private static MockHttpServletRequest request(String clientTraceId, String gatewayRequestId) {
        MockHttpServletRequest request = new MockHttpServletRequest();
        if (clientTraceId != null) {
            request.addHeader(TraceId.HEADER, clientTraceId);
        }
        if (gatewayRequestId != null) {
            request.addHeader(TraceId.GATEWAY_REQUEST_ID_HEADER, gatewayRequestId);
        }
        return request;
    }

    private String traceIdFor(String clientTraceId, String gatewayRequestId) throws Exception {
        MockHttpServletResponse response = new MockHttpServletResponse();
        filter.doFilter(request(clientTraceId, gatewayRequestId), response, new MockFilterChain());
        return response.getHeader(TraceId.HEADER);
    }
}
