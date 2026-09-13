# SupplyNext ML Service

Demand forecasting and reorder planning for SupplyNext — **Phase C** of the
project roadmap.

This is a standalone Python microservice that sits alongside the Spring Boot
backend. It does not replace any Phase B analytics; it extends them from
*backward-looking* (what did we sell?) to *forward-looking* (what will we
sell, and what should we do about it?).

---

## Why a separate service?

Phase B's analytics — EOQ, ABC, safety stock, reorder point — are all closed-form
formulas, and Java handles those perfectly well. Time-series forecasting is
different: it needs model fitting, backtesting, and numerical optimisation, and
Python's `pandas` / `statsmodels` / `numpy` stack is genuinely years ahead of
anything on the JVM for that work.

Splitting it out also keeps responsibilities clean:

| | Spring backend | ML service |
|---|---|---|
| Owns business transactions | yes | no |
| Writes to the database | yes | **never** |
| Authenticates users | yes | no (see Security below) |
| Fits statistical models | no | yes |

---

## How forecasting works here

1. **Build a gap-free daily series.** Sales-order line items are grouped by
   date and summed. Days with no sales become `0` — this matters more than it
   sounds. If you only average the days that *had* sales, you systematically
   overestimate demand and over-order.

2. **Fit several candidate models:**

   | Model | What it captures | Good for |
   |---|---|---|
   | `naive` | tomorrow = today | the baseline everything must beat |
   | `moving_average` | recent average | flat, noisy demand |
   | `ses` | exponentially weighted average | flat demand, recent days matter more |
   | `holt` | level + trend | steadily growing or shrinking demand |
   | `holt_winters` | level + trend + weekly cycle | day-of-week rhythms |

3. **Backtest.** Hide the last *N* days from each model, ask it to predict them,
   and score the result with MAE, RMSE and sMAPE.

   > sMAPE rather than plain MAPE on purpose: MAPE divides by the actual value,
   > which blows up to infinity on the zero-demand days that fill real inventory
   > data. sMAPE divides by the average of actual and predicted, so it stays finite.

4. **Pick the winner** (lowest MAE) and forecast forward with it. That is
   `model="auto"`, and it is the honest way to choose — rather than assuming one
   model is always best. The API returns the full comparison table so you can see
   what was tried and why the winner won.

5. **Add a prediction interval** from the spread of the model's own residuals.

### Stated tradeoff

The prediction interval is **constant across the horizon**. In reality
uncertainty grows the further out you forecast, so a day-30 interval should be
wider than a day-1 interval. Modelling that properly means per-model variance
formulas (or bootstrapped simulation paths). The current intervals are honest
about average error but **slightly optimistic far out** — worth knowing before
quoting a 30-day bound to anyone.

---

## Running it

### Locally

```bash
cd ml-service
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

uvicorn app.main:app --reload --port 8000
```

Then open **http://localhost:8000/docs** for interactive Swagger docs — the same
idea as the backend's `/swagger-ui.html`.

### With Docker

From the repository root:

```bash
docker compose up ml-service
```

### Tests

```bash
pytest -q          # 46 tests, no database required
```

---

## Two ways to use it

### 1. Stateless — no database needed

Send the history, get a forecast. **This is the mode the Spring backend should
use in production**, because it keeps the backend as the only component that
owns the data.

```bash
curl -X POST http://localhost:8000/api/forecast/demand \
  -H "Content-Type: application/json" \
  -d '{
    "observations": [
      {"observed_on": "2026-06-01", "quantity": 8},
      {"observed_on": "2026-06-02", "quantity": 12}
    ],
    "horizon_days": 30,
    "model": "auto"
  }'
```

### 2. Database-backed — convenient for demos

Set `DATABASE_URL` and the service reads the SupplyNext schema directly.

```bash
DATABASE_URL=postgresql+psycopg2://postgres:1234@localhost:5432/scm_db \
  uvicorn app.main:app --port 8000
```

```bash
curl http://localhost:8000/api/forecast/product/1?horizon_days=30
```

> **Tradeoff, stated plainly:** this reads the same database the Spring backend
> owns. Two services now depend on one schema, so a backend migration can break
> this one. It is done this way because the access is strictly read-only,
> forecasting needs bulk history that would be slow to page through a REST API,
> and it lets Phase C ship without modifying the Spring codebase at all.
>
> If the schema starts churning, add a `GET /api/analytics/demand-history`
> endpoint to the backend and point `app/repository.py` at it. That module is
> the only thing that would need to change.

---

## Endpoints

| Method | Path | Database? | Purpose |
|---|---|---|---|
| GET | `/health` | no | Liveness + DB connectivity |
| POST | `/api/forecast/demand` | no | Forecast from supplied history |
| POST | `/api/forecast/reorder-plan` | no | Forecast + reorder recommendation |
| GET | `/api/forecast/product/{id}` | yes | Forecast one product |
| GET | `/api/forecast/products` | yes | Forecast every product with history |
| GET | `/api/forecast/reorder-plan/{id}` | yes | Full reorder plan for one product |
| GET | `/docs` | no | Interactive Swagger UI |

### Reorder planning

`reorder-plan` turns a forecast into the decision a warehouse manager actually
needs. It reuses Phase B's formulas so the two agree — the difference is that
the demand input is a **forecast** rather than a historical mean:

- **demand during lead time** — forecast summed over the next `lead_time_days`
- **safety stock** — `Z × σ(daily demand) × √(lead time)` (same as Phase B)
- **reorder point** — lead-time demand + safety stock
- **should reorder now** — stock has fallen to or below the reorder point
- **projected stockout date** — first day the running balance hits zero
- **recommended order quantity** — enough to cover the horizon plus safety
  stock, less what is already on hand

Lead time defaults to the product's supplier `leadTimeDays` — the same field
Phase B's safety-stock endpoint reads.

---

## Consistency with the Spring backend

Demand is counted **only from `SHIPPED` sales orders**, keyed on `orderDate` —
exactly matching `AnalyticsService.computeDemandStats()`. A `PENDING` order is
a request, not a fulfilled sale; counting it would inflate every forecast.

If you ever change that rule on one side, change it on the other, or EOQ and
the forecast will quietly contradict each other. The setting is
`DEMAND_ORDER_STATUS` in `.env`.

---

## Security — read this before deploying

**This service currently has no authentication.** Anyone who can reach port 8000
can call it.

That is acceptable for local development, and it is deliberately flagged rather
than silently glossed over. Before this is exposed anywhere real, pick one:

1. **Don't expose it.** Keep it on an internal network and let only the Spring
   backend call it. Simplest and probably correct — in Docker Compose it is
   already only reachable by name from inside the Compose network.
2. **Validate the same JWT** the backend issues (shared secret, verify the
   signature in a FastAPI dependency).
3. **Put a shared API key** in front of it as a middleware check.

Option 1 plus dropping the public port mapping is the recommended path.

---

## Layout

```
ml-service/
├── app/
│   ├── main.py          FastAPI routes + error handling (HTTP only)
│   ├── forecasting.py   the forecasting engine (no framework imports)
│   ├── planning.py      forecast -> reorder decision
│   ├── repository.py    read-only SQL against the SupplyNext schema
│   ├── database.py      optional SQLAlchemy engine
│   ├── schemas.py       Pydantic request/response models
│   └── config.py        environment-driven settings
├── tests/               46 tests, no database required
├── Dockerfile
└── requirements.txt
```

The layering mirrors the backend's own convention: `main.py` is the controller
(HTTP only, no business logic), `forecasting.py` / `planning.py` are the service
layer, and `repository.py` is the data layer. `forecasting.py` imports no web
framework at all, which is what makes it straightforward to unit test.
