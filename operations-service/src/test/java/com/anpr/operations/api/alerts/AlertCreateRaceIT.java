package com.anpr.operations.api.alerts;

import com.anpr.operations.TestcontainersConfiguration;
import com.anpr.operations.internal.alerts.repository.AlertRepository;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;

import java.util.UUID;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.doReturn;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/**
 * Two creates of the same plate that both pass the existence check: the second one must hit the unique constraint of
 * the real database and still return 409. The check is stubbed to false to reproduce the race without threads.
 * A separate class because the spy changes the Spring context of every test in it.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@Import(TestcontainersConfiguration.class)
class AlertCreateRaceIT {

    @Autowired
    private MockMvc mockMvc;

    @MockitoSpyBean
    private AlertRepository alertRepository;

    @Test
    void secondCreateThatPassedTheExistenceCheckReturns409() throws Exception {
        doReturn(false).when(alertRepository).existsByAccountIdAndPlate(any(), anyString());
        String account = UUID.randomUUID().toString();

        create(account).andExpect(status().isCreated());

        create(account)
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.code").value("ALERT_ALREADY_EXISTS"))
                .andExpect(jsonPath("$.requestId").exists());
    }

    private ResultActions create(String account) throws Exception {
        return mockMvc.perform(post("/api/v1/alerts")
                .header("X-Account-Id", account)
                .contentType(MediaType.APPLICATION_JSON)
                .content("""
                        { "plate": "PO11111" }
                        """));
    }
}
