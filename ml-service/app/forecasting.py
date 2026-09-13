"""
Demand forecasting engine for SupplyNext.

This module is deliberately framework-free: it knows nothing about FastAPI,
HTTP, or the database. It takes a list of historical sales observations and
returns a forecast. That keeps it trivially unit-testable (see
tests/test_forecasting.py) and reusable from anywhere.

The forecasting approach, in plain terms
----------------------------------------
1. Turn raw sales-order line items into a regular daily time series.
   Days with no sales become 0 — this matters. If you only look at days that
   had sales, you systematically overestimate demand.

2. Fit several candidate models to the history.

3. Backtest: hide the most recent `holdout` days from each model, ask it to
   predict them, and measure how close it got (MAE / RMSE / sMAPE).

4. Pick the model with the lowest MAE and use it for the real forecast.
   This is "auto" mode, and it is the honest way to choose — rather than
   assuming one model is always best.

5. Build a prediction interval from the spread of the model's own residuals.

Models used
-----------
- naive            : tomorrow looks like today. The baseline every other
                     model must beat to justify its complexity.
- moving_average   : mean of the last N days. Smooths noise, ignores trend.
- ses              : Simple Exponential Smoothing. Weighted average where
                     recent days count more. Good for flat, noisy demand.
- holt             : SES + a trend component. Good for growing/shrinking demand.
- holt_winters     : Holt + a repeating weekly pattern. Good when demand has
                     a day-of-week rhythm (very common in retail/distribution).
"""

from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

# statsmodels emits a lot of convergence chatter on short series. We handle
# failures explicitly below, so the warnings are noise rather than signal.
warnings.filterwarnings("ignore")

try:
    from statsmodels.tsa.holtwinters import (
        ExponentialSmoothing,
        Holt,
        SimpleExpSmoothing,
    )

    STATSMODELS_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only in degraded installs
    STATSMODELS_AVAILABLE = False


# --- Tunables -----------------------------------------------------------

SEASONAL_PERIOD = 7          # weekly rhythm for daily data
MIN_POINTS_FOR_FORECAST = 7  # below this we refuse rather than guess
MIN_POINTS_FOR_TREND = 10    # Holt needs a bit of runway to see a trend
MIN_POINTS_FOR_SEASONAL = 2 * SEASONAL_PERIOD + 1
DEFAULT_MOVING_AVERAGE_WINDOW = 7
DEFAULT_HOLDOUT_DAYS = 7

# z-scores for two-sided prediction intervals
Z_SCORES = {0.80: 1.2816, 0.90: 1.6449, 0.95: 1.9600, 0.99: 2.5758}


# --- Result types -------------------------------------------------------


@dataclass
class Observation:
    """One historical demand data point."""

    observed_on: date
    quantity: float


@dataclass
class ForecastPoint:
    forecast_date: date
    predicted_quantity: float
    lower_bound: float
    upper_bound: float


@dataclass
class ModelEvaluation:
    """How a single model scored during backtesting."""

    model: str
    mae: float | None
    rmse: float | None
    smape: float | None
    failed_reason: str | None = None

    @property
    def usable(self) -> bool:
        return self.mae is not None


@dataclass
class ForecastResult:
    model_used: str
    horizon_days: int
    points: list[ForecastPoint]
    total_forecast_quantity: float
    mean_daily_demand: float
    history_days: int
    history_total_quantity: float
    evaluations: list[ModelEvaluation] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


class InsufficientHistoryError(ValueError):
    """Raised when there is too little history to forecast responsibly."""


# --- Series construction ------------------------------------------------


def build_daily_series(
    observations: Iterable[Observation],
    *,
    end_on: date | None = None,
) -> pd.Series:
    """
    Collapse raw observations into a gap-free daily series.

    Multiple observations on the same day are summed (a product can appear on
    several sales orders in one day). Days between the first and last
    observation with no sales are filled with 0, because "no sale" is real
    demand information, not missing data.

    `end_on` extends the series forward to that date with zeros — use it to
    say "it is 2026-09-13 today and nothing has sold since August", which is
    exactly what a dead-stock-aware forecast needs to know.
    """
    observations = list(observations)
    if not observations:
        return pd.Series(dtype="float64")

    frame = pd.DataFrame(
        {
            "observed_on": [pd.Timestamp(o.observed_on) for o in observations],
            "quantity": [float(o.quantity) for o in observations],
        }
    )
    daily = frame.groupby("observed_on")["quantity"].sum().sort_index()

    last = daily.index.max()
    if end_on is not None and pd.Timestamp(end_on) > last:
        last = pd.Timestamp(end_on)

    full_range = pd.date_range(start=daily.index.min(), end=last, freq="D")
    return daily.reindex(full_range, fill_value=0.0).astype("float64")


# --- Individual models --------------------------------------------------


def _fit_predict(model: str, train: pd.Series, horizon: int) -> np.ndarray:
    """
    Fit `model` on `train` and return `horizon` predictions.

    Raises ValueError when the model cannot be fitted on this series (too
    short, no variance, solver failure). Callers treat that as "this model is
    not a candidate" rather than as a fatal error.
    """
    values = train.to_numpy(dtype="float64")
    n = len(values)

    if n < MIN_POINTS_FOR_FORECAST:
        raise ValueError(f"need at least {MIN_POINTS_FOR_FORECAST} days of history")

    if model == "naive":
        return np.repeat(values[-1], horizon)

    if model == "moving_average":
        window = min(DEFAULT_MOVING_AVERAGE_WINDOW, n)
        return np.repeat(values[-window:].mean(), horizon)

    if not STATSMODELS_AVAILABLE:
        raise ValueError("statsmodels is not installed")

    if model == "ses":
        fitted = SimpleExpSmoothing(values, initialization_method="estimated").fit()
        return np.asarray(fitted.forecast(horizon), dtype="float64")

    if model == "holt":
        if n < MIN_POINTS_FOR_TREND:
            raise ValueError(f"need at least {MIN_POINTS_FOR_TREND} days for a trend model")
        fitted = Holt(values, initialization_method="estimated").fit()
        return np.asarray(fitted.forecast(horizon), dtype="float64")

    if model == "holt_winters":
        if n < MIN_POINTS_FOR_SEASONAL:
            raise ValueError(
                f"need at least {MIN_POINTS_FOR_SEASONAL} days for weekly seasonality"
            )
        fitted = ExponentialSmoothing(
            values,
            trend="add",
            seasonal="add",
            seasonal_periods=SEASONAL_PERIOD,
            initialization_method="estimated",
        ).fit()
        return np.asarray(fitted.forecast(horizon), dtype="float64")

    raise ValueError(f"unknown model: {model}")


def available_models(history_length: int) -> list[str]:
    """Which models can even be attempted for a series of this length."""
    models = ["naive", "moving_average"]
    if STATSMODELS_AVAILABLE:
        models.append("ses")
        if history_length >= MIN_POINTS_FOR_TREND:
            models.append("holt")
        if history_length >= MIN_POINTS_FOR_SEASONAL:
            models.append("holt_winters")
    return models


# --- Accuracy metrics ---------------------------------------------------


def _mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(np.abs(actual - predicted)))


def _rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - predicted) ** 2)))


def _smape(actual: np.ndarray, predicted: np.ndarray) -> float:
    """
    Symmetric MAPE, as a percentage.

    Plain MAPE divides by the actual value, which explodes to infinity on the
    zero-demand days that are everywhere in real inventory data. sMAPE divides
    by the average of actual and predicted instead, so it stays finite.
    """
    denominator = (np.abs(actual) + np.abs(predicted)) / 2.0
    safe = np.where(denominator == 0, 1.0, denominator)
    ratio = np.where(denominator == 0, 0.0, np.abs(actual - predicted) / safe)
    return float(np.mean(ratio) * 100.0)


# --- Backtesting and model selection ------------------------------------


def evaluate_models(
    series: pd.Series,
    *,
    holdout: int = DEFAULT_HOLDOUT_DAYS,
) -> list[ModelEvaluation]:
    """
    Backtest every candidate model against a held-out tail of the history.

    Returns one ModelEvaluation per candidate, sorted best-MAE-first. Models
    that could not be fitted are included with `failed_reason` set, so the API
    can be honest about what was tried rather than silently dropping them.
    """
    n = len(series)
    # Keep the holdout small enough that the training window is still the
    # majority of the data.
    holdout = max(1, min(holdout, n // 3))

    train = series.iloc[:-holdout]
    test = series.iloc[-holdout:].to_numpy(dtype="float64")

    results: list[ModelEvaluation] = []
    for model in available_models(len(train)):
        try:
            predicted = _fit_predict(model, train, holdout)
        except Exception as exc:  # noqa: BLE001 - any solver failure disqualifies
            results.append(
                ModelEvaluation(model=model, mae=None, rmse=None, smape=None,
                                failed_reason=str(exc))
            )
            continue

        predicted = np.clip(predicted, 0.0, None)
        results.append(
            ModelEvaluation(
                model=model,
                mae=round(_mae(test, predicted), 4),
                rmse=round(_rmse(test, predicted), 4),
                smape=round(_smape(test, predicted), 4),
            )
        )

    usable = [r for r in results if r.usable]
    failed = [r for r in results if not r.usable]
    usable.sort(key=lambda r: r.mae)
    return usable + failed


def select_best_model(evaluations: Sequence[ModelEvaluation]) -> str:
    """Lowest MAE wins; fall back to the naive baseline if nothing fitted."""
    for evaluation in evaluations:
        if evaluation.usable:
            return evaluation.model
    return "naive"


# --- Top-level forecast -------------------------------------------------


def forecast(
    series: pd.Series,
    *,
    horizon_days: int = 30,
    model: str = "auto",
    confidence_level: float = 0.95,
    holdout: int = DEFAULT_HOLDOUT_DAYS,
) -> ForecastResult:
    """
    Produce a demand forecast for the next `horizon_days`.

    `model="auto"` backtests every candidate and uses the winner. Naming a
    model explicitly skips selection and forces that one.
    """
    if horizon_days < 1:
        raise ValueError("horizon_days must be at least 1")

    n = len(series)
    if n < MIN_POINTS_FOR_FORECAST:
        raise InsufficientHistoryError(
            f"Only {n} day(s) of history available; "
            f"at least {MIN_POINTS_FOR_FORECAST} are required to forecast."
        )

    notes: list[str] = []
    evaluations: list[ModelEvaluation] = []

    if model == "auto":
        evaluations = evaluate_models(series, holdout=holdout)
        chosen = select_best_model(evaluations)
        if not any(e.usable for e in evaluations):
            notes.append(
                "No model could be backtested successfully; fell back to the "
                "naive baseline. Treat this forecast as a placeholder."
            )
    else:
        chosen = model

    try:
        predictions = _fit_predict(chosen, series, horizon_days)
    except Exception as exc:  # noqa: BLE001
        if model != "auto":
            raise
        notes.append(f"{chosen} failed on the full history ({exc}); used naive instead.")
        chosen = "naive"
        predictions = _fit_predict("naive", series, horizon_days)

    # Demand cannot be negative. Holt in particular will happily extrapolate a
    # downward trend straight through zero.
    predictions = np.clip(predictions, 0.0, None)

    # Prediction interval from in-sample residual spread. This is a simplifying
    # assumption (it treats uncertainty as constant across the horizon rather
    # than widening with distance) — see README for the tradeoff note.
    residual_std = _residual_std(series, chosen)
    z = Z_SCORES.get(round(confidence_level, 2), 1.9600)
    margin = z * residual_std

    start = series.index.max().date() + timedelta(days=1)
    points = [
        ForecastPoint(
            forecast_date=start + timedelta(days=offset),
            predicted_quantity=round(float(value), 2),
            lower_bound=round(max(0.0, float(value) - margin), 2),
            upper_bound=round(float(value) + margin, 2),
        )
        for offset, value in enumerate(predictions)
    ]

    if n < 30:
        notes.append(
            f"Based on only {n} days of history — treat as a rough estimate."
        )
    if float(series.sum()) == 0.0:
        notes.append("No sales at all in the observed window; forecast is zero by construction.")

    total = float(np.sum(predictions))
    return ForecastResult(
        model_used=chosen,
        horizon_days=horizon_days,
        points=points,
        total_forecast_quantity=round(total, 2),
        mean_daily_demand=round(total / horizon_days, 4),
        history_days=n,
        history_total_quantity=round(float(series.sum()), 2),
        evaluations=list(evaluations),
        notes=notes,
    )


def _residual_std(series: pd.Series, model: str) -> float:
    """
    Standard deviation of one-step-ahead in-sample errors.

    Falls back to the series' own standard deviation when the model cannot be
    re-fitted, which keeps the interval non-zero rather than pretending to
    perfect certainty.
    """
    values = series.to_numpy(dtype="float64")
    try:
        if model == "naive":
            residuals = values[1:] - values[:-1]
        elif model == "moving_average":
            window = min(DEFAULT_MOVING_AVERAGE_WINDOW, len(values) - 1)
            rolling = pd.Series(values).rolling(window).mean().shift(1)
            residuals = (pd.Series(values) - rolling).dropna().to_numpy()
        else:
            if not STATSMODELS_AVAILABLE:
                raise ValueError("statsmodels unavailable")
            if model == "ses":
                fitted = SimpleExpSmoothing(values, initialization_method="estimated").fit()
            elif model == "holt":
                fitted = Holt(values, initialization_method="estimated").fit()
            else:
                fitted = ExponentialSmoothing(
                    values,
                    trend="add",
                    seasonal="add",
                    seasonal_periods=SEASONAL_PERIOD,
                    initialization_method="estimated",
                ).fit()
            residuals = np.asarray(fitted.resid, dtype="float64")
    except Exception:  # noqa: BLE001
        residuals = values - values.mean()

    residuals = residuals[np.isfinite(residuals)]
    if residuals.size < 2:
        return float(np.std(values)) if values.size else 0.0

    std = float(np.std(residuals, ddof=1))
    return std if math.isfinite(std) else 0.0
