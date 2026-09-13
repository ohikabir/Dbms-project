# What's new, and how to add it to your repo

Everything here is either a **brand-new file** or a **replacement for an
existing file at the same path**. Nothing needs to be deleted, and no file
needs to be hand-edited after uploading — dropping them in at the right paths
is enough.

> This guide is scaffolding for the upload. Once everything is in, you can
> delete `UPLOAD_GUIDE.md` itself.

---

## Easiest route: upload the whole folder at once

On GitHub (works in a mobile browser if you switch to **Desktop site**):

1. Open your repo → **Add file** → **Upload files**
2. Drag in the folders (`ml-service`, `postman`, `.github`, `backend`,
   `frontend`) and the loose root files
3. GitHub preserves folder structure on upload, and a file uploaded to an
   existing path replaces that file
4. Commit

If the mobile UI fights you, the reliable fallback is **Files → upload one
folder at a time**, committing between each.

---

## New files

### `ml-service/` — Phase C, the ML forecasting microservice

| File | |
|---|---|
| `app/main.py` | FastAPI routes, error handling |
| `app/forecasting.py` | The forecasting engine — 5 models, backtesting, model selection |
| `app/planning.py` | Turns a forecast into a reorder decision |
| `app/repository.py` | Read-only SQL against your existing schema |
| `app/database.py` | Optional SQLAlchemy engine |
| `app/schemas.py` | Pydantic request/response models |
| `app/config.py` | Environment-driven settings |
| `app/__init__.py` | *(one-line docstring — makes `app` a package)* |
| `tests/test_forecasting.py` | 21 tests |
| `tests/test_planning.py` | 11 tests |
| `tests/test_api.py` | 14 tests |
| `tests/__init__.py` | *(one-line docstring, required)* |
| `requirements.txt`, `pytest.ini`, `Dockerfile`, `.dockerignore`, `.gitignore`, `.env.example`, `README.md` | |

> Both `__init__.py` files contain a one-line docstring rather than being
> empty. That is deliberate: GitHub's uploader silently skips zero-byte files,
> and without these two `import app` fails. Make sure they arrive.

### `postman/` — the collection you'd been meaning to build

- `SupplyNext.postman_collection.json` — 44 requests, auto-captures the JWT on login
- `SupplyNext.postman_environment.json`
- `README.md`

### `.github/workflows/ci.yml` — CI

Runs backend, ML and frontend test suites in parallel on every push.

### Docker

- `docker-compose.yml` *(root)* — whole stack incl. PostgreSQL
- `.env.example` *(root)*
- `backend/Dockerfile`, `backend/.dockerignore`
- `frontend/Dockerfile`, `frontend/.dockerignore`

### `README.md` *(root)*

Architecture diagram, ER diagram, API reference, role matrix, tradeoffs. Both
diagrams are Mermaid, which GitHub renders automatically.

---

## Replacements

These overwrite files you already have. **The four backend ones are the
integration-test fix — they only work as a set.**

| Path | What changed |
|---|---|
| `backend/src/test/resources/application-test.properties` | Removed the invalid `spring.profiles.active=test` line |
| `backend/src/main/java/com/example/scmbackend/security/SecurityConfig.java` | Removed the duplicate test-profile bean; production chain and CORS untouched |
| `backend/src/test/java/com/example/scmbackend/security/TestSecurityConfig.java` | Now the only test security chain, with the 401 entry point |
| `backend/src/test/java/com/example/scmbackend/warehouse/WarehouseIntegrationTest.java` | `@Disabled` removed; MockMvc built with `springSecurity()` |
| `backend/src/test/java/com/example/scmbackend/ScmBackendApplicationTests.java` | Added `@ActiveProfiles("test")` so it uses H2, not your local Postgres |
| `frontend/next.config.ts` | Added `output: "standalone"` (needed by the Dockerfile; no effect on `npm run dev`) |
| `TODO.md` | Updated status |
| `.gitignore` | Added Python and `.env` rules |

---

## After uploading — check it worked

```bash
cd backend    && ./mvnw test     # expect 48/48, no database needed
cd ml-service && pip install -r requirements.txt && pytest -q   # expect 46/46
```

The GitHub Actions run will do both for you automatically on the push.

To try the ML service:

```bash
cd ml-service
uvicorn app.main:app --reload --port 8000
```

Then open http://localhost:8000/docs and try `POST /api/forecast/demand`.
The Postman collection's folder 12 has a ready-made request with 28 days of
sample data that has a weekend spike in it — Holt-Winters should win the
model comparison on it.
