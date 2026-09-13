package com.example.scmbackend.warehouse;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.security.test.context.support.WithMockUser;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.security.test.web.servlet.setup.SecurityMockMvcConfigurers;
import org.springframework.web.context.WebApplicationContext;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

/**
 * End-to-end integration test: real HTTP -> Security filter chain ->
 * Controller -> Service -> H2 database.
 *
 * This test was disabled for a long time with all four cases returning 403.
 * CORS was suspected, but was never the cause. There were three real bugs,
 * stacked on top of each other:
 *
 *  1. src/test/resources/application-test.properties set
 *     "spring.profiles.active=test". Spring Boot rejects that property inside
 *     a profile-specific file (InvalidConfigDataPropertyException), so the
 *     application context failed to build and every test errored out before
 *     any request was made. @ActiveProfiles("test") below already activates
 *     the profile, so the property was both invalid and redundant.
 *
 *  2. SecurityConfig and TestSecurityConfig both declared a @Profile("test")
 *     bean named testSecurityFilterChain -> BeanDefinitionOverrideException.
 *     The test chain now lives only in TestSecurityConfig.
 *
 *  3. @WithMockUser had no effect because MockMvc was injected directly
 *     instead of being built with SecurityMockMvcConfigurers.springSecurity().
 *     Without that, the mock user is never placed into the security context,
 *     so authenticated cases came back 401. Building MockMvc explicitly in
 *     setUp() fixes it and makes the wiring visible rather than implicit.
 */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class WarehouseIntegrationTest {

    @Autowired
    private WebApplicationContext webApplicationContext;

    private MockMvc mockMvc;

    @BeforeEach
    void setUp() {
        mockMvc = MockMvcBuilders.webAppContextSetup(webApplicationContext)
                .apply(SecurityMockMvcConfigurers.springSecurity())
                .build();
    }

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    void shouldReturn401_whenNoAuthTokenProvided() throws Exception {
        mockMvc.perform(get("/api/warehouses")
                        .header("Origin", "http://localhost:3000"))
                .andExpect(status().isUnauthorized());
    }

    @Test
    @WithMockUser(roles = "ADMIN")
    void shouldCreateWarehouse_whenAuthenticatedAsAdmin() throws Exception {
        WarehouseRequestDto request = new WarehouseRequestDto();
        request.setName("Test Warehouse");
        request.setLocation("Dhaka");
        request.setCapacity(1000);

        mockMvc.perform(post("/api/warehouses")
                        .header("Origin", "http://localhost:3000")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.name").value("Test Warehouse"))
                .andExpect(jsonPath("$.location").value("Dhaka"))
                .andExpect(jsonPath("$.capacity").value(1000));
    }

    @Test
    @WithMockUser(roles = "ADMIN")
    void shouldReturnValidationError_whenNameIsBlank() throws Exception {
        WarehouseRequestDto request = new WarehouseRequestDto();
        request.setName("");
        request.setLocation("Dhaka");
        request.setCapacity(1000);

        mockMvc.perform(post("/api/warehouses")
                        .header("Origin", "http://localhost:3000")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest());
    }

    @Test
    @WithMockUser(roles = "STAFF")
    void shouldReturn403_whenStaffTriesToCreateWarehouse() throws Exception {
        WarehouseRequestDto request = new WarehouseRequestDto();
        request.setName("Test Warehouse");
        request.setLocation("Dhaka");
        request.setCapacity(1000);

        mockMvc.perform(post("/api/warehouses")
                        .header("Origin", "http://localhost:3000")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isForbidden());
    }
}
