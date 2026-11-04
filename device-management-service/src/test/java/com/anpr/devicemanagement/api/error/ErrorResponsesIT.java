package com.anpr.devicemanagement.api.error;

import com.anpr.devicemanagement.support.ApiTestSupport;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;

import java.util.UUID;

import static org.hamcrest.Matchers.containsString;
import static org.hamcrest.Matchers.not;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** Conventions every error response follows (RFC 9457 problem, stable code, trace id, nothing internal). */
class ErrorResponsesIT extends ApiTestSupport {

    @Test
    void anErrorIsAProblemWithCodeAndTheTraceIdOfTheRequest() throws Exception {
        mockMvc.perform(get("/api/v1/device").with(person(UUID.randomUUID())).header("X-Trace-Id", "trace-abc-1"))
                .andExpect(status().isNotFound())
                .andExpect(header().string("X-Trace-Id", "trace-abc-1"))
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.status").value(404))
                .andExpect(jsonPath("$.code").value("DEVICE_NOT_FOUND"))
                .andExpect(jsonPath("$.requestId").value("trace-abc-1"))
                .andExpect(content().string(not(containsString("com.anpr"))));
    }

    @Test
    void withoutAClientTraceIdTheRequestIdOfTheGatewayIsTheTraceId() throws Exception {
        mockMvc.perform(get("/api/v1/device").with(person(UUID.randomUUID())).header("X-Request-Id", "JZoPFhq3FiAEMbA="))
                .andExpect(header().string("X-Trace-Id", "JZoPFhq3FiAEMbA="))
                .andExpect(jsonPath("$.requestId").value("JZoPFhq3FiAEMbA="));
    }

    @Test
    void anInvalidTraceIdIsReplacedByAGeneratedOne() throws Exception {
        mockMvc.perform(get("/api/v1/device").with(person(UUID.randomUUID())).header("X-Trace-Id", "not valid!"))
                .andExpect(header().string("X-Trace-Id", not("not valid!")))
                .andExpect(jsonPath("$.requestId").isNotEmpty());
    }

    @Test
    void aRequestThatBypassedTheGatewayIsUnauthenticated() throws Exception {
        mockMvc.perform(get("/api/v1/device"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("UNAUTHENTICATED"));
    }

    @Test
    void anUnreadableBodyRevealsNoParserDetails() throws Exception {
        PersonWithDevice owner = createPersonWithDevice();

        mockMvc.perform(post("/api/v1/device/metrics").with(device(owner.deviceId()))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{ \"metrics\": [ { \"gps\": { \"fix\": \"fix_3d\" } } ] }"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("INVALID_REQUEST"))
                .andExpect(content().string(not(containsString("jackson"))))
                .andExpect(content().string(not(containsString("com.anpr"))));
    }
}
