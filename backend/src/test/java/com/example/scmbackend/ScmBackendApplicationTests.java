package com.example.scmbackend;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

/**
 * Smoke test: proves the whole Spring application context can be built.
 *
 * @ActiveProfiles("test") points this at the in-memory H2 database from
 * src/test/resources/application-test.properties. Without it, the test falls
 * back to the real application.properties and tries to open a PostgreSQL
 * connection on localhost:5432 — so it only passed on a machine that happened
 * to have Postgres running, and failed anywhere else (CI included).
 */
@SpringBootTest
@ActiveProfiles("test")
class ScmBackendApplicationTests {

    @Test
    void contextLoads() {
    }

}
