# SupplyNext — TODO / Current Status

## Completed

### Phase A — Architecture & Engineering

- [x] Full backend CRUD for all 8 modules (Warehouse, Category, Supplier,
      Product, Inventory, PurchaseOrder, SalesOrder, Transfer)
- [x] JWT authentication (register/login) + BCrypt password hashing
- [x] Role-based access control (ADMIN, WAREHOUSE_MANAGER, STAFF)
- [x] Service layer refactor (business logic out of controllers)
- [x] DTO refactor (Request/Response DTOs, flattened responses)
- [x] Pagination on every list GET endpoint (backend + frontend)
- [x] Swagger/OpenAPI docs (`/swagger-ui.html`) with JWT bearer-auth button
- [x] Global exception handling (clean JSON errors, no stack trace leakage)
- [x] Unit tests for all service classes
- [x] Full frontend: login, protected layout w/ sidebar, all 8 module pages
- [x] Dashboard aggregate endpoint + frontend cards

### Phase B — Smart Analytics

- [x] EOQ, ABC Analysis, Safety Stock, Reorder Point, Dead Stock Detection,
      Supplier Analytics, KPI Dashboard expansion — all backend + frontend,
      21 unit tests, verified end-to-end
- [x] Charts via recharts (bar + pie) on the unified `/analytics` page
- [x] Bug fix: `SupplierAnalyticsResponseDto` miscounted legacy RECEIVED POs
      (added `receivedWithoutDateCount` to separate "truly pending" from
      "received but untracked"). Found by cross-checking supplier-performance
      against the dashboard summary — that kind of cross-KPI consistency check
      is worth repeating on future analytics work.

### Phase C — ML Demand Forecasting

- [x] `ml-service/` — standalone FastAPI microservice
- [x] Five forecasting models (naive, moving average, SES, Holt, Holt-Winters)
      with automatic backtest-driven model selection (MAE / RMSE / sMAPE)
- [x] Prediction intervals from residual spread
- [x] Reorder planning: lead-time demand, safety stock, reorder point,
      projected stockout date, recommended order quantity — reuses Phase B's
      formulas so the two agree, but fed a forecast instead of a historical mean
- [x] Stateless endpoints (no DB) + optional database-backed endpoints
- [x] 46 tests, no database required
- [x] Swagger UI at `/docs`, Dockerfile, README with tradeoffs documented

### Phase E — Deployment & DevOps (partial)

- [x] Dockerfiles for backend (multi-stage JDK→JRE), frontend (Next.js
      standalone) and ml-service, all running as non-root
- [x] `docker-compose.yml` — full stack incl. PostgreSQL, with health checks
      and correct startup ordering
- [x] GitHub Actions CI — backend, ml-service and frontend jobs in parallel
- [ ] Hosting decision + actual deployment (Render / Railway / Fly.io /
      Oracle Cloud Free Tier were the free-tier-friendly options discussed)

### Phase F — Documentation (partial)

- [x] Root `README.md` with architecture diagram, ER diagram, API reference,
      role matrix and a stated-tradeoffs section
- [x] Postman collection formalized — `postman/`, 44 requests, environment
      variables, automatic token capture on login
- [ ] Screenshots of the running UI
- [ ] Demo video

### Fixed — previously parked bugs

- [x] **WarehouseIntegrationTest — FIXED, all 4 cases passing.**
      CORS was suspected for a long time and was never the cause. Three real
      bugs were stacked on top of each other:
      1. `application-test.properties` set `spring.profiles.active=test`.
         Spring Boot rejects that property inside a profile-specific file
         (`InvalidConfigDataPropertyException`), so the application context
         never built and all 4 tests errored before any HTTP call was made.
         `@ActiveProfiles("test")` already activates it — the line was both
         invalid and redundant.
      2. `SecurityConfig` and `TestSecurityConfig` both declared a
         `@Profile("test")` bean named `testSecurityFilterChain` →
         `BeanDefinitionOverrideException`. The test chain now lives only in
         `TestSecurityConfig` (in test sources, where it belongs).
      3. `@WithMockUser` had no effect because `MockMvc` was injected directly
         rather than built with `SecurityMockMvcConfigurers.springSecurity()`,
         so authenticated cases returned 401.
      Production CORS config was not touched.

- [x] **`ScmBackendApplicationTests` had no `@ActiveProfiles("test")`**, so the
      context test tried to open a real PostgreSQL connection on
      localhost:5432. It only passed on a machine that happened to have
      Postgres running, and would have failed in CI. Now runs against H2 like
      the rest of the suite.

**Backend suite: 48/48 passing. ML suite: 46/46 passing. Neither needs a
database.**

## Open

- [ ] **PATCH /api/products/{id} role enforcement — unverified.**
      Testing with a STAFF token returned 401 instead of the expected 403. GET
      with the same token succeeded (200), which rules out an expired token.
      Suspected Postman-side issue (Authorization tab vs Headers tab conflict)
      rather than a real SecurityConfig bug, since the PATCH rule matches the
      working PurchaseOrder/Transfer/Inventory ones exactly. NOT CONFIRMED —
      revisit before relying on this restriction for anything sensitive.
      The new Postman collection sets auth once at the collection level, which
      should make this easy to retest cleanly.

- [ ] **Wire the ML service into the Spring backend.** The service works and is
      callable, but nothing in the backend calls it yet. The clean approach:
      add a small `ForecastClient` (`RestClient`) that POSTs sales history to
      `/api/forecast/demand`, so the backend stays the only owner of the data.

- [ ] **Frontend page for forecasting.** No UI yet — a `/forecasting` page with
      a history-vs-forecast line chart (recharts is already installed) and the
      reorder recommendation would complete Phase C visually.

## Backlog

- Phase D: UI/UX polish — search/filter on tables, dark mode, responsive
  design. (Toasts via sonner, skeleton loaders and status badges are already
  partly in place.)
- Phase E: pick a host and actually deploy.
- Phase F: screenshots, demo video.

## Known Tech Debt (deliberate, tracked, not urgent)

- JWT secret key hardcoded in `JwtUtil.java` — move to an env var before any
  real deployment. `.env.example` has a placeholder ready for it.
- JWT expiration is 7 days (bumped from 10 hours) for dev convenience — a real
  deployment wants short-lived tokens + a refresh token pattern.
- Frontend stores the JWT in `localStorage` rather than an httpOnly cookie.
- `spring.jpa.hibernate.ddl-auto=update` — production wants Flyway/Liquibase.
- The ML service has **no authentication**. Keep it off the public internet, or
  put JWT validation / an API key in front of it. See `ml-service/README.md`.
- The ML service reads the backend's database directly in its DB-backed mode.
  Read-only, but it does couple two services to one schema — `app/repository.py`
  is the single place that would change if this moves to an API call instead.
- Forecast prediction intervals are constant-width across the horizon rather
  than widening with distance — honest on average, slightly optimistic far out.

## Rules / Conventions for Continuing This Project

- Follow the existing layered pattern (Controller → Service → Repository) and
  DTO pattern (flattened Response DTOs, validated Request DTOs) for any new
  module — don't introduce a different pattern without discussing it first.
- The person is learning Spring Boot as they go — provide full working code to
  copy-paste, with concept explanations alongside, not terse code dumps. Move
  faster through genuinely repetitive patterns they've seen many times.
- Always flag deliberate shortcuts/tradeoffs explicitly (security, tech debt)
  rather than silently taking them.
- Test in Postman/browser after each meaningful change; commit to git with a
  descriptive message after each confirmed-working feature.
- The current codebase (GitHub repo) is the source of truth. If this document
  and the actual code ever disagree, trust the code.
