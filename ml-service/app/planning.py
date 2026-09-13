"""
Turns a forecast into an inventory decision.

The forecasting module answers "how much will we sell?". This module answers
the question a warehouse manager actually asks: "do I need to order, when will
I run out, and how much should I buy?"

It mirrors the formulas already implemented in the Spring backend's
AnalyticsService (safety stock, reorder point) so the two agree — the
difference is the demand input. Phase B uses the historical mean; here the
same formulas are fed a forward-looking forecast instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from .forecasting import Z_SCORES, ForecastResult

# Matches AnalyticsService's service-level handling on the Java side.
DEFAULT_SERVICE_LEVEL = 0.95


@dataclass
class ReorderPlan:
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
    notes: list[str]


def _z_for(service_level: float) -> float:
    """Nearest tabulated z-score, defaulting to the 95% value."""
    if not Z_SCORES:
        return 1.96
    nearest = min(Z_SCORES, key=lambda level: abs(level - service_level))
    return Z_SCORES[nearest]


def build_reorder_plan(
    result: ForecastResult,
    history: pd.Series,
    *,
    current_stock: float,
    lead_time_days: int,
    service_level: float = DEFAULT_SERVICE_LEVEL,
) -> ReorderPlan:
    """
    Combine a forecast with the current stock position into a buy/don't-buy call.

    - demand during lead time : sum of the forecast over the next `lead_time_days`
    - safety stock            : Z x sigma(daily demand) x sqrt(lead time)
                                (the classic formula, same as Phase B)
    - reorder point           : lead-time demand + safety stock
    - should reorder now      : stock has fallen to or below the reorder point
    - stockout date           : first day the running stock balance hits zero
    - recommended quantity    : enough to cover the full forecast horizon plus
                                safety stock, less what is already on hand
    """
    notes: list[str] = list(result.notes)

    daily = np.array([p.predicted_quantity for p in result.points], dtype="float64")

    if lead_time_days > len(daily):
        # Asking for a 30-day lead time from a 14-day forecast would silently
        # under-count demand. Extend with the forecast's own mean instead.
        shortfall = lead_time_days - len(daily)
        mean = float(daily.mean()) if daily.size else 0.0
        lead_time_demand = float(daily.sum()) + mean * shortfall
        notes.append(
            f"Lead time ({lead_time_days}d) exceeds the forecast horizon "
            f"({len(daily)}d); the remaining {shortfall}d were extrapolated "
            "at the forecast's mean daily demand."
        )
    else:
        lead_time_demand = float(daily[:lead_time_days].sum())

    # Variability comes from actual history, not from the forecast — the
    # forecast is a smoothed central estimate and would understate real spread.
    daily_std = float(history.std(ddof=1)) if len(history) > 1 else 0.0
    if not math.isfinite(daily_std):
        daily_std = 0.0

    z = _z_for(service_level)
    safety_stock = z * daily_std * math.sqrt(max(lead_time_days, 0))
    reorder_point = lead_time_demand + safety_stock

    should_reorder = current_stock <= reorder_point

    stockout_date = _project_stockout(result, current_stock)
    if stockout_date is None and daily.sum() > 0:
        notes.append(
            f"Stock is not projected to run out within the {result.horizon_days}-day "
            "forecast horizon."
        )

    horizon_demand = float(daily.sum())
    recommended = max(0.0, horizon_demand + safety_stock - current_stock)
    if not should_reorder:
        recommended = 0.0

    return ReorderPlan(
        current_stock=round(current_stock, 2),
        lead_time_days=lead_time_days,
        service_level=service_level,
        forecast_demand_during_lead_time=round(lead_time_demand, 2),
        safety_stock=round(safety_stock, 2),
        reorder_point=round(reorder_point, 2),
        should_reorder_now=should_reorder,
        projected_stockout_date=stockout_date,
        recommended_order_quantity=round(recommended, 2),
        model_used=result.model_used,
        notes=notes,
    )


def _project_stockout(result: ForecastResult, current_stock: float) -> date | None:
    """Walk the forecast day by day and return the first day stock hits zero."""
    balance = current_stock
    for point in result.points:
        balance -= point.predicted_quantity
        if balance <= 0:
            return point.forecast_date
    return None
