"""
Unit tests for the forecasting engine.

Mirrors the backend's testing style: each test names the behaviour it pins
down, and the assertions are about business meaning (demand is never
negative, a seasonal series picks a seasonal model) rather than exact floats,
which would make the suite brittle against solver changes.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from app.forecasting import (
    InsufficientHistoryError,
    Observation,
    build_daily_series,
    evaluate_models,
    forecast,
    select_best_model,
)

START = date(2026, 1, 1)


def _observations(quantities: list[float], start: date = START) -> list[Observation]:
    return [
        Observation(observed_on=start + timedelta(days=i), quantity=q)
        for i, q in enumerate(quantities)
    ]


# --- build_daily_series -------------------------------------------------


def test_buildDailySeries_fillsMissingDaysWithZero():
    observations = [
        Observation(observed_on=date(2026, 1, 1), quantity=5),
        Observation(observed_on=date(2026, 1, 4), quantity=3),
    ]
    series = build_daily_series(observations)

    assert len(series) == 4, "Jan 1 through Jan 4 inclusive"
    assert list(series.values) == [5.0, 0.0, 0.0, 3.0]


def test_buildDailySeries_sumsMultipleObservationsOnSameDay():
    observations = [
        Observation(observed_on=date(2026, 1, 1), quantity=5),
        Observation(observed_on=date(2026, 1, 1), quantity=7),
    ]
    series = build_daily_series(observations)

    assert len(series) == 1
    assert series.iloc[0] == 12.0


def test_buildDailySeries_extendsToEndOnWithZeros():
    """A product that stopped selling must show zeros, not a truncated series."""
    observations = [Observation(observed_on=date(2026, 1, 1), quantity=5)]
    series = build_daily_series(observations, end_on=date(2026, 1, 10))

    assert len(series) == 10
    assert series.iloc[0] == 5.0
    assert series.iloc[1:].sum() == 0.0


def test_buildDailySeries_returnsEmptyForNoObservations():
    assert build_daily_series([]).empty


# --- forecast guardrails ------------------------------------------------


def test_forecast_rejectsTooShortHistory():
    series = build_daily_series(_observations([1, 2, 3]))

    with pytest.raises(InsufficientHistoryError):
        forecast(series, horizon_days=7)


def test_forecast_rejectsNonPositiveHorizon():
    series = build_daily_series(_observations([5] * 30))

    with pytest.raises(ValueError):
        forecast(series, horizon_days=0)


def test_forecast_neverPredictsNegativeDemand():
    """
    A steep downward trend makes Holt extrapolate straight through zero.
    Negative demand is meaningless, so it must be clamped.
    """
    series = build_daily_series(_observations([float(x) for x in range(30, 0, -1)]))
    result = forecast(series, horizon_days=30, model="holt")

    assert all(p.predicted_quantity >= 0 for p in result.points)
    assert all(p.lower_bound >= 0 for p in result.points)


def test_forecast_returnsRequestedNumberOfPoints():
    series = build_daily_series(_observations([5] * 40))
    result = forecast(series, horizon_days=14)

    assert len(result.points) == 14


def test_forecast_startsDayAfterHistoryEnds():
    series = build_daily_series(_observations([5] * 30))
    result = forecast(series, horizon_days=5)

    assert result.points[0].forecast_date == START + timedelta(days=30)


def test_forecast_boundsBracketThePrediction():
    series = build_daily_series(_observations([5, 7, 3, 9, 4, 6, 8] * 5))
    result = forecast(series, horizon_days=10)

    for point in result.points:
        assert point.lower_bound <= point.predicted_quantity <= point.upper_bound


# --- model behaviour ----------------------------------------------------


def test_forecast_constantSeriesPredictsThatConstant():
    series = build_daily_series(_observations([10.0] * 40))
    result = forecast(series, horizon_days=7)

    for point in result.points:
        assert point.predicted_quantity == pytest.approx(10.0, abs=0.5)


def test_forecast_zeroSeriesForecastsZeroAndSaysSo():
    series = build_daily_series(_observations([0.0] * 40))
    result = forecast(series, horizon_days=7)

    assert result.total_forecast_quantity == pytest.approx(0.0, abs=0.01)
    assert any("No sales at all" in note for note in result.notes)


def test_forecast_upwardTrendForecastsAboveHistoricalMean():
    quantities = [float(x) for x in range(1, 41)]
    series = build_daily_series(_observations(quantities))
    result = forecast(series, horizon_days=10, model="holt")

    assert result.mean_daily_demand > float(np.mean(quantities))


def test_forecast_explicitModelIsHonoured():
    series = build_daily_series(_observations([5] * 40))
    result = forecast(series, horizon_days=7, model="moving_average")

    assert result.model_used == "moving_average"
    assert result.evaluations == [], "no backtesting when a model is forced"


def test_forecast_autoModeRunsBacktestAndPicksAModel():
    series = build_daily_series(_observations([5, 7, 3, 9, 4, 6, 8] * 6))
    result = forecast(series, horizon_days=7, model="auto")

    assert result.evaluations, "auto mode must report what it compared"
    assert result.model_used in {e.model for e in result.evaluations}


def test_forecast_shortHistoryIsFlaggedAsRough():
    series = build_daily_series(_observations([5] * 20))
    result = forecast(series, horizon_days=7)

    assert any("rough estimate" in note for note in result.notes)


# --- backtesting --------------------------------------------------------


def test_evaluateModels_scoresEveryCandidate():
    series = build_daily_series(_observations([5, 7, 3, 9, 4, 6, 8] * 6))
    evaluations = evaluate_models(series, holdout=7)

    assert len(evaluations) >= 3
    names = {e.model for e in evaluations}
    assert {"naive", "moving_average"} <= names


def test_evaluateModels_sortsUsableResultsBestFirst():
    series = build_daily_series(_observations([5, 7, 3, 9, 4, 6, 8] * 6))
    usable = [e for e in evaluate_models(series, holdout=7) if e.usable]

    maes = [e.mae for e in usable]
    assert maes == sorted(maes)


def test_evaluateModels_perfectPredictionScoresZeroError():
    series = build_daily_series(_observations([4.0] * 40))
    usable = [e for e in evaluate_models(series, holdout=7) if e.usable]

    assert min(e.mae for e in usable) == pytest.approx(0.0, abs=0.01)


def test_selectBestModel_fallsBackToNaiveWhenNothingFitted():
    from app.forecasting import ModelEvaluation

    failed = [ModelEvaluation(model="ses", mae=None, rmse=None, smape=None,
                              failed_reason="boom")]
    assert select_best_model(failed) == "naive"


def test_evaluateModels_seasonalSeriesBeatsNaiveWithSeasonalModel():
    """
    A strong weekly pattern is exactly what Holt-Winters exists for; it should
    outscore the naive baseline on a cleanly seasonal series.
    """
    week = [2.0, 2.0, 2.0, 2.0, 2.0, 20.0, 20.0]  # weekend spike
    series = build_daily_series(_observations(week * 8))
    evaluations = {e.model: e for e in evaluate_models(series, holdout=7)}

    if "holt_winters" in evaluations and evaluations["holt_winters"].usable:
        assert evaluations["holt_winters"].mae <= evaluations["naive"].mae
