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
 * returned in the response header.
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
        String traceId = traceIdOf(request);
        MDC.put(TraceId.MDC_KEY, traceId);
        response.setHeader(TraceId.HEADER, traceId);
        try {
            chain.doFilter(request, response);
        } finally {
            MDC.remove(TraceId.MDC_KEY);
        }
    }

    private static String traceIdOf(HttpServletRequest request) {
        String client = request.getHeader(TraceId.HEADER);
        if (client != null && CLIENT_TRACE_ID.matcher(client).matches()) {
            return client;
        }
        String gateway = request.getHeader(TraceId.GATEWAY_REQUEST_ID_HEADER);
        if (gateway != null && GATEWAY_REQUEST_ID.matcher(gateway).matches()) {
            return gateway;
        }
        return UUID.randomUUID().toString();
    }
}
