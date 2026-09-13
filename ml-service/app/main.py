"""
SupplyNext ML service — FastAPI application.

Phase C of the SupplyNext roadmap: demand forecasting as a separate Python
microservice, sitting alongside the Spring Boot backend rather than inside it.

Why a separate service at all? Forecasting is where Python's ecosystem
(pandas, statsmodels, numpy) is genuinely far ahead of the JVM's. Keeping it
behind its own HTTP boundary means the Spring backend stays the single owner
of business transactions, and this service stays a stateless calculator that
can be scaled, redeployed, or swapped out independently.

Two ways to use it:

  1. Stateless (no database needed) — POST the history, get a forecast back.
     This is the endpoint the Spring backend should call in production, since
     it keeps the backend as the only component that owns the data.

  2. Database-backed (set DATABASE_URL) — the service reads the SupplyNext
     schema directly. Convenient for demos and local development; see
     app/database.py for the tradeoff this makes.

Interactive API docs: http://localhost:8000/docs
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import planning, repository
from .config import get_settings
from .database import database_reachable
from .forecasting import (
    STATSMODELS_AVAILABLE,
    InsufficientHistoryError,
    Observation,
    build_daily_series,
    forecast,
)
from .repository import DatabaseNotConfiguredError
from .schemas import (
    ForecastRequest,
    ForecastResponse,
    HealthResponse,
    ReorderPlanRequest,
    ReorderPlanResponse,
)

settings = get_settings()

app = FastAPI(
    title="SupplyNext ML Service",
    description=(
        "Demand forecasting and reorder planning for the SupplyNext supply "
        "chain management system."
    ),
    version=settings.version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Error handling -----------------------------------------------------
#
# Mirrors the Spring backend's GlobalExceptionHandler: business errors come
# back as clean JSON with the same field names, never as a stack trace.


def _error_body(status: int, error: str, message: str, path: str) -> dict:
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "error": error,
        "message": message,
        "path": path,
    }


@app.exception_handler(InsufficientHistoryError)
async def handle_insufficient_history(request: Request, exc: InsufficientHistoryError):
    return JSONResponse(
        status_code=422,
        content=_error_body(422, "Unprocessable Entity", str(exc), request.url.path),
    )


@app.exception_handler(DatabaseNotConfiguredError)
async def handle_no_database(request: Request, exc: DatabaseNotConfiguredError):
    return JSONResponse(
        status_code=503,
        content=_error_body(503, "Service Unavailable", str(exc), request.url.path),
    )


@app.exception_handler(ValueError)
async def handle_value_error(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=400,
        content=_error_body(400, "Bad Request", str(exc), request.url.path),
    )


# --- Health -------------------------------------------------------------


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    """Liveness probe. Also reports whether the optional DB link is working."""
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        version=settings.version,
        statsmodels_available=STATSMODELS_AVAILABLE,
        database_configured=settings.database_configured,
        database_reachable=database_reachable(),
    )


# --- Stateless forecasting ---------------------------------------------


def _to_response(result, product_id=None, product_name=None) -> ForecastResponse:
    return ForecastResponse(
        product_id=product_id,
        product_name=product_name,
        model_used=result.model_used,
        horizon_days=result.horizon_days,
        total_forecast_quantity=result.total_forecast_quantity,
        mean_daily_demand=result.mean_daily_demand,
        history_days=result.history_days,
        history_total_quantity=result.history_total_quantity,
        points=[p.__dict__ for p in result.points],
        model_comparison=[e.__dict__ for e in result.evaluations],
        notes=result.notes,
    )


@app.post("/api/forecast/demand", response_model=ForecastResponse, tags=["forecast"])
def forecast_demand(request: ForecastRequest) -> ForecastResponse:
    """
    Forecast demand from history supplied in the request body.

    Needs no database, which makes this the endpoint to call from the Spring
    backend (it already has the sales history) and the easiest one to try in
    Postman or Swagger.
    """
    observations = [
        Observation(observed_on=o.observed_on, quantity=o.quantity)
        for o in request.observations
    ]
    series = build_daily_series(observations)

    result = forecast(
        series,
        horizon_days=request.horizon_days,
        model=request.model,
        confidence_level=request.confidence_level,
    )
    return _to_response(result, request.product_id, request.product_name)


@app.post("/api/forecast/reorder-plan", response_model=ReorderPlanResponse, tags=["forecast"])
def reorder_plan(request: ReorderPlanRequest) -> ReorderPlanResponse:
    """Forecast, then turn it into a reorder recommendation. Stateless."""
    observations = [
        Observation(observed_on=o.observed_on, quantity=o.quantity)
        for o in request.observations
    ]
    series = build_daily_series(observations)

    result = forecast(
        series,
        horizon_days=max(request.horizon_days, request.lead_time_days),
        model=request.model,
        confidence_level=request.confidence_level,
    )
    plan = planning.build_reorder_plan(
        result,
        series,
        current_stock=request.current_stock,
        lead_time_days=request.lead_time_days,
        service_level=request.service_level,
    )
    return ReorderPlanResponse(
        product_id=request.product_id,
        product_name=request.product_name,
        **{k: v for k, v in plan.__dict__.items()},
    )


# --- Database-backed forecasting ---------------------------------------


@app.get(
    "/api/forecast/product/{product_id}",
    response_model=ForecastResponse,
    tags=["forecast (database)"],
)
def forecast_product(
    product_id: int,
    horizon_days: int = Query(default=None, ge=1, le=365),
    model: str = Query(default="auto"),
) -> ForecastResponse:
    """Forecast one product, reading its history straight from the database."""
    horizon_days = horizon_days or settings.default_horizon_days

    product = repository.fetch_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product not found: {product_id}")

    observations = repository.fetch_demand_history(product_id)
    if not observations:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No {settings.demand_order_status} sales history for product "
                f"{product_id}; nothing to forecast from."
            ),
        )

    series = build_daily_series(observations, end_on=repository.fetch_latest_order_date())
    result = forecast(series, horizon_days=horizon_days, model=model)
    return _to_response(result, product.id, product.name)


@app.get(
    "/api/forecast/products",
    response_model=list[ForecastResponse],
    tags=["forecast (database)"],
)
def forecast_all_products(
    horizon_days: int = Query(default=None, ge=1, le=365),
    model: str = Query(default="auto"),
) -> list[ForecastResponse]:
    """
    Forecast every product that has enough history.

    Products with too little history are skipped rather than returned with a
    made-up number — a fabricated forecast is worse than no forecast.
    """
    horizon_days = horizon_days or settings.default_horizon_days

    products = repository.fetch_products()
    history_by_product = repository.fetch_demand_history_bulk()
    latest = repository.fetch_latest_order_date()

    responses: list[ForecastResponse] = []
    for product in products:
        observations = history_by_product.get(product.id, [])
        if not observations:
            continue
        series = build_daily_series(observations, end_on=latest)
        try:
            result = forecast(series, horizon_days=horizon_days, model=model)
        except InsufficientHistoryError:
            continue
        responses.append(_to_response(result, product.id, product.name))

    responses.sort(key=lambda r: r.total_forecast_quantity, reverse=True)
    return responses


@app.get(
    "/api/forecast/reorder-plan/{product_id}",
    response_model=ReorderPlanResponse,
    tags=["forecast (database)"],
)
def reorder_plan_for_product(
    product_id: int,
    horizon_days: int = Query(default=None, ge=1, le=365),
    service_level: float = Query(default=None, ge=0.5, le=0.999),
    lead_time_days: int = Query(default=None, ge=0, le=365),
) -> ReorderPlanResponse:
    """
    Full reorder recommendation for one product, straight from the database.

    Lead time comes from the product's supplier when the query parameter is
    omitted — the same `leadTimeDays` field Phase B's safety-stock endpoint uses.
    """
    horizon_days = horizon_days or settings.default_horizon_days
    service_level = service_level or settings.default_service_level

    product = repository.fetch_product(product_id)
    if product is None:
        raise HTTPException(status_code=404, detail=f"Product not found: {product_id}")

    if lead_time_days is None:
        lead_time_days = product.lead_time_days or settings.default_lead_time_days

    observations = repository.fetch_demand_history(product_id)
    if not observations:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No {settings.demand_order_status} sales history for product "
                f"{product_id}; cannot build a reorder plan."
            ),
        )

    series = build_daily_series(observations, end_on=repository.fetch_latest_order_date())
    result = forecast(series, horizon_days=max(horizon_days, lead_time_days))

    plan = planning.build_reorder_plan(
        result,
        series,
        current_stock=repository.fetch_total_stock(product_id),
        lead_time_days=lead_time_days,
        service_level=service_level,
    )
    if product.lead_time_days is None:
        plan.notes.append(
            f"Supplier has no leadTimeDays set; used the default of "
            f"{settings.default_lead_time_days} days. Set it on the supplier "
            "for a more accurate plan."
        )

    return ReorderPlanResponse(
        product_id=product.id,
        product_name=product.name,
        **{k: v for k, v in plan.__dict__.items()},
    )
