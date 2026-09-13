"""
Pydantic models describing the ML service's HTTP contract.

These mirror the SupplyNext backend's DTO convention: validated request
shapes, flattened response shapes, no leaking of internal structures.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

ModelName = Literal["auto", "naive", "moving_average", "ses", "holt", "holt_winters"]


# --- Requests -----------------------------------------------------------


class ObservationIn(BaseModel):
    """One historical demand data point supplied by the caller."""

    observed_on: date = Field(..., description="Date the demand occurred")
    quantity: float = Field(..., ge=0, description="Units sold that day")


class ForecastRequest(BaseModel):
    """
    Stateless forecast input.

    Use this when the caller already has the history (e.g. the Spring backend
    queried it, or you are testing from Postman). The service does not need
    database access for this endpoint.
    """

    observations: list[ObservationIn] = Field(..., min_length=1)
    horizon_days: int = Field(30, ge=1, le=365)
    model: ModelName = "auto"
    confidence_level: float = Field(0.95, ge=0.5, le=0.99)
    product_id: int | None = None
    product_name: str | None = None

    @field_validator("observations")
    @classmethod
    def reject_duplicate_free_empty(cls, value: list[ObservationIn]) -> list[ObservationIn]:
        if not value:
            raise ValueError("at least one observation is required")
        return value


class ReorderPlanRequest(ForecastRequest):
    """Forecast input plus the stock position needed for a reorder decision."""

    current_stock: float = Field(..., ge=0, description="Units on hand right now")
    lead_time_days: int = Field(7, ge=0, le=365)
    service_level: float = Field(0.95, ge=0.5, le=0.999)


# --- Responses ----------------------------------------------------------


class ForecastPointOut(BaseModel):
    forecast_date: date
    predicted_quantity: float
    lower_bound: float
    upper_bound: float


class ModelEvaluationOut(BaseModel):
    model: str
    mae: float | None = None
    rmse: float | None = None
    smape: float | None = None
    failed_reason: str | None = None


class ForecastResponse(BaseModel):
    product_id: int | None = None
    product_name: str | None = None

    model_used: str
    horizon_days: int
    total_forecast_quantity: float
    mean_daily_demand: float

    history_days: int
    history_total_quantity: float

    points: list[ForecastPointOut]
    model_comparison: list[ModelEvaluationOut] = []
    notes: list[str] = []

    # `model_used` / `model_comparison` start with "model_", which Pydantic v2
    # reserves by default. Turning the protected namespace off keeps the field
    # names readable instead of forcing something like `selected_model`.
    model_config = {"protected_namespaces": ()}


class ReorderPlanResponse(BaseModel):
    product_id: int | None = None
    product_name: str | None = None

    current_stock: float
    lead_time_days: int
    service_level: float

    forecast_demand_during_lead_time: float
    safety_stock: float
    reorder_point: float
    should_reorder_now: bool
    projected_stockout_date: date | None
    recommended_order_quantity: float

    model_used: str
    notes: list[str] = []

    model_config = {"protected_namespaces": ()}


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    statsmodels_available: bool
    database_configured: bool
    database_reachable: bool | None = None


class ErrorResponse(BaseModel):
    """Matches the Spring backend's ErrorResponse shape for consistency."""

    timestamp: str
    status: int
    error: str
    message: str
    path: str
