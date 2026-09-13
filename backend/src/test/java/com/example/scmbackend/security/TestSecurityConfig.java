package com.example.scmbackend.security;

import jakarta.servlet.http.HttpServletResponse;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Profile;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;

/**
 * The ONLY security filter chain active under the "test" profile.
 *
 * Why this class exists at all: integration tests drive the app through
 * MockMvc with @WithMockUser, so the real JwtAuthFilter (which expects a
 * signed "Authorization: Bearer ..." header) would reject every request.
 * This chain keeps the authorization RULES identical to production but drops
 * the JWT filter, so @WithMockUser can populate the security context instead.
 *
 * Two things that previously broke this, both fixed here:
 *
 *  1. SecurityConfig also declared a @Profile("test") bean named
 *     testSecurityFilterChain. Two beans with the same name under the same
 *     profile is a hard BeanDefinitionOverrideException — the application
 *     context never loaded, so every test errored before a single HTTP call
 *     was made. The test chain now lives here (in test sources) and ONLY
 *     here; SecurityConfig's production chain is marked @Profile("!test").
 *
 *  2. Without an explicit authenticationEntryPoint, Spring Security defaults
 *     to Http403ForbiddenEntryPoint when no login mechanism is configured —
 *     so unauthenticated requests return 403 instead of 401. Setting the
 *     entry point restores the 401-vs-403 distinction the tests assert on.
 *
 * Note: CORS is deliberately NOT configured here. It was long suspected as
 * the cause of the blanket 403s, but it never was — and leaving it out of
 * the test chain means production CORS config stays untouched.
 */
@Configuration
@Profile("test")
public class TestSecurityConfig {

    @Bean
    public SecurityFilterChain testSecurityFilterChain(HttpSecurity http) throws Exception {
        http
                .csrf(csrf -> csrf.disable())
                .exceptionHandling(ex -> ex
                        .authenticationEntryPoint((request, response, authException) ->
                                response.sendError(HttpServletResponse.SC_UNAUTHORIZED, "Unauthorized"))
                )
                .authorizeHttpRequests(auth -> auth
                        .requestMatchers("/api/auth/**").permitAll()
                        .requestMatchers("/v3/api-docs/**", "/swagger-ui/**", "/swagger-ui.html").permitAll()
                        .requestMatchers(HttpMethod.POST, "/api/warehouses", "/api/categories", "/api/suppliers", "/api/products").hasAnyRole("ADMIN", "WAREHOUSE_MANAGER")
                        .requestMatchers(HttpMethod.POST, "/api/purchase-orders/**", "/api/transfers/**").hasAnyRole("ADMIN", "WAREHOUSE_MANAGER")
                        .requestMatchers(HttpMethod.PATCH, "/api/purchase-orders/**", "/api/transfers/**", "/api/inventory/**", "/api/products/**", "/api/suppliers/**").hasAnyRole("ADMIN", "WAREHOUSE_MANAGER")
                        .requestMatchers(HttpMethod.POST, "/api/sales-orders/**").hasAnyRole("ADMIN", "WAREHOUSE_MANAGER", "STAFF")
                        .requestMatchers(HttpMethod.PATCH, "/api/sales-orders/**").hasAnyRole("ADMIN", "WAREHOUSE_MANAGER", "STAFF")
                        .anyRequest().authenticated()
                );

        return http.build();
    }
}
