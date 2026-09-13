"""Unit tests for reorder planning — the forecast-to-decision layer."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.forecasting import Observation, build_daily_series, forecast
from app.planning import build_reorder_plan

START = date(2026, 1, 1)


def _steady_series(daily: float = 10.0, days: int = 40):
    observations = [
        Observation(observed_on=START + timedelta(days=i), quantity=daily)
        for i in range(days)
    ]
    return build_daily_series(observations)


def _plan(current_stock: float, lead_time_days: int = 7, daily: float = 10.0):
    series = _steady_series(daily=daily)
    result = forecast(series, horizon_days=30, model="moving_average")
    return build_reorder_plan(
        result,
        series,
        current_stock=current_stock,
        lead_time_days=lead_time_days,
    )


def test_reorderPlan_lowStockTriggersReorder():
    plan = _plan(current_stock=5.0)

    assert plan.should_reorder_now is True
    assert plan.recommended_order_quantity > 0


def test_reorderPlan_ampleStockDoesNotTriggerReorder():
    plan = _plan(current_stock=10_000.0)

    assert plan.should_reorder_now is False
    assert plan.recommended_order_quantity == 0.0


def test_reorderPlan_leadTimeDemandMatchesSteadyDailyRate():
    """10 units/day over a 7-day lead time is 70 units."""
    plan = _plan(current_stock=0.0, lead_time_days=7, daily=10.0)

    assert plan.forecast_demand_during_lead_time == pytest.approx(70.0, abs=1.0)


def test_reorderPlan_steadyDemandHasNoSafetyStock():
    """Zero variability means zero safety stock — the formula must not invent risk."""
    plan = _plan(current_stock=0.0)

    assert plan.safety_stock == pytest.approx(0.0, abs=0.01)


def test_reorderPlan_variableDemandRequiresSafetyStock():
    observations = [
        Observation(observed_on=START + timedelta(days=i), quantity=q)
        for i, q in enumerate([2, 18, 5, 15, 9, 11, 20] * 6)
    ]
    series = build_daily_series(observations)
    result = forecast(series, horizon_days=30, model="moving_average")
    plan = build_reorder_plan(result, series, current_stock=0.0, lead_time_days=7)

    assert plan.safety_stock > 0


def test_reorderPlan_reorderPointIsLeadTimeDemandPlusSafetyStock():
    plan = _plan(current_stock=0.0)

    expected = plan.forecast_demand_during_lead_time + plan.safety_stock
    assert plan.reorder_point == pytest.approx(expected, abs=0.02)


def test_reorderPlan_projectsStockoutDate():
    """50 units on hand at 10/day runs out on day 5 of the forecast."""
    plan = _plan(current_stock=50.0)

    assert plan.projected_stockout_date == START + timedelta(days=40 + 4)


def test_reorderPlan_noStockoutWithinHorizonIsReportedAsNone():
    plan = _plan(current_stock=10_000.0)

    assert plan.projected_stockout_date is None
    assert any("not projected to run out" in note for note in plan.notes)


def test_reorderPlan_leadTimeBeyondHorizonIsExtrapolatedAndFlagged():
    series = _steady_series()
    result = forecast(series, horizon_days=10, model="moving_average")
    plan = build_reorder_plan(result, series, current_stock=0.0, lead_time_days=30)

    assert plan.forecast_demand_during_lead_time == pytest.approx(300.0, abs=5.0)
    assert any("exceeds the forecast horizon" in note for note in plan.notes)


def test_reorderPlan_higherServiceLevelRaisesSafetyStock():
    observations = [
        Observation(observed_on=START + timedelta(days=i), quantity=q)
        for i, q in enumerate([2, 18, 5, 15, 9, 11, 20] * 6)
    ]
    series = build_daily_series(observations)
    result = forecast(series, horizon_days=30, model="moving_average")

    at_90 = build_reorder_plan(result, series, current_stock=0.0,
                               lead_time_days=7, service_level=0.90)
    at_99 = build_reorder_plan(result, series, current_stock=0.0,
                               lead_time_days=7, service_level=0.99)

    assert at_99.safety_stock > at_90.safety_stock


def test_reorderPlan_zeroLeadTimeNeedsNoLeadTimeCover():
    plan = _plan(current_stock=0.0, lead_time_days=0)

    assert plan.forecast_demand_during_lead_time == 0.0
    assert plan.safety_stock == 0.0
