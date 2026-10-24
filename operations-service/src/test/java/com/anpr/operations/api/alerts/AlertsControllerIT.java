package com.anpr.operations.api.alerts;

import com.anpr.operations.TestcontainersConfiguration;
import com.jayway.jsonpath.JsonPath;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import java.util.UUID;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@Import(TestcontainersConfiguration.class)
class AlertsControllerIT {

    private static final String ACCOUNT_HEADER = "X-Account-Id";

    @Autowired
    private MockMvc mockMvc;

    @Test
    void createAlertReturns201() throws Exception {
        String account = UUID.randomUUID().toString();

        mockMvc.perform(post("/api/v1/alerts")
                        .header(ACCOUNT_HEADER, account)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "plate": "WA12345", "alertText": "Stolen" }
                                """))
                .andExpect(status().isCreated())
                .andExpect(header().exists("Location"))
                .andExpect(jsonPath("$.plate").value("WA12345"))
                .andExpect(jsonPath("$.version").value(0));
    }

    @Test
    void duplicatePlateReturns409() throws Exception {
        String account = UUID.randomUUID().toString();
        createAlert(account, "KR98765");

        mockMvc.perform(post("/api/v1/alerts")
                        .header(ACCOUNT_HEADER, account)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "plate": "KR98765" }
                                """))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("ALERT_ALREADY_EXISTS"))
                .andExpect(jsonPath("$.requestId").exists());
    }

    @Test
    void invalidPlateReturns400() throws Exception {
        mockMvc.perform(post("/api/v1/alerts")
                        .header(ACCOUNT_HEADER, UUID.randomUUID().toString())
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "plate": "wa 12" }
                                """))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"))
                .andExpect(jsonPath("$.fields[0].field").value("plate"));
    }

    @Test
    void alertOfAnotherAccountReturns404() throws Exception {
        String alertId = createAlert(UUID.randomUUID().toString(), "GD11111");

        mockMvc.perform(get("/api/v1/alerts/{id}", alertId)
                        .header(ACCOUNT_HEADER, UUID.randomUUID().toString()))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.code").value("ALERT_NOT_FOUND"));
    }

    @Test
    void updateWithStaleVersionReturns409() throws Exception {
        String account = UUID.randomUUID().toString();
        String alertId = createAlert(account, "PO55555");

        mockMvc.perform(put("/api/v1/alerts/{id}", alertId)
                        .header(ACCOUNT_HEADER, account)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                { "plate": "PO55555", "alertText": "Changed", "version": 7 }
                                """))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("CONCURRENT_MODIFICATION"));
    }

    @Test
    void missingAccountHeaderReturns401() throws Exception {
        mockMvc.perform(get("/api/v1/alerts"))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.code").value("UNAUTHENTICATED"));
    }

    private String createAlert(String account, String plate) throws Exception {
        String body = mockMvc.perform(post("/api/v1/alerts")
                        .header(ACCOUNT_HEADER, account)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{ \"plate\": \"" + plate + "\" }"))
                .andExpect(status().isCreated())
                .andReturn().getResponse().getContentAsString();
        return JsonPath.read(body, "$.alertId");
    }
}