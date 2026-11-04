package com.anpr.operations.shared.tracing;

import lombok.AccessLevel;
import lombok.NoArgsConstructor;
import org.slf4j.MDC;

import java.util.Optional;

/** The trace id of the request being handled, kept in the MDC so that every log line and published event carries it. */
@NoArgsConstructor(access = AccessLevel.PRIVATE)
public final class TraceId {
    public static final String HEADER = "X-Trace-Id";
    /** Injected by API Gateway: its own id of the request, the one in its access logs. */
    public static final String GATEWAY_REQUEST_ID_HEADER = "X-Request-Id";
    public static final String MDC_KEY = "traceId";

    public static Optional<String> current() {
        return Optional.ofNullable(MDC.get(MDC_KEY));
    }
}
