package com.anpr.devicemanagement.shared.tracing;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.MDC;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.UUID;
import java.util.regex.Pattern;

/**
 * Sets the trace id of the request, by the same rule as the ingest Lambda: the client's {@code X-Trace-Id} when it is
 * a plain token, otherwise the request id of API Gateway ({@code X-Request-Id}, which the gateway always overwrites),
 * otherwise a new one (a call that bypassed the gateway). The id is in the MDC for the duration of the request and
 * returned in the response header. When the client's id wins, the gateway's id is in the MDC too (gatewayRequestId),
 * because the access logs of API Gateway know only their own id.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class TraceIdFilter extends OncePerRequestFilter {
    private static final Pattern CLIENT_TRACE_ID = Pattern.compile("[A-Za-z0-9-]{1,64}");
    /** API Gateway request ids are base64-like, e.g. {@code JZoPFhq3FiAEMbA=}. */
    private static final Pattern GATEWAY_REQUEST_ID = Pattern.compile("[A-Za-z0-9+/=-]{1,128}");

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        String client = valid(request.getHeader(TraceId.HEADER), CLIENT_TRACE_ID);
        String gateway = valid(request.getHeader(TraceId.GATEWAY_REQUEST_ID_HEADER), GATEWAY_REQUEST_ID);
        String traceId = client != null ? client : gateway != null ? gateway : UUID.randomUUID().toString();

        MDC.put(TraceId.MDC_KEY, traceId);
        if (client != null && gateway != null) {
            MDC.put(TraceId.GATEWAY_REQUEST_ID_MDC_KEY, gateway);
        }
        response.setHeader(TraceId.HEADER, traceId);
        try {
            chain.doFilter(request, response);
        } finally {
            MDC.remove(TraceId.MDC_KEY);
            MDC.remove(TraceId.GATEWAY_REQUEST_ID_MDC_KEY);
        }
    }

    /** The header value when it matches the pattern; otherwise null, as if it was not sent. */
    private static String valid(String value, Pattern pattern) {
        return value != null && pattern.matcher(value).matches() ? value : null;
    }
}
