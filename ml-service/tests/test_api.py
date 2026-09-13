"""
API-level tests using FastAPI's TestClient.

These cover the HTTP contract — status codes, response shape, error handling —
without needing a database. Only the stateless endpoints are exercised here,
which is the point: they are the ones the Spring backend will call.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)
START = date(2026, 1, 1)


def _payload(days: int = 40, quantity: float = 10.0, **extra) -> dict:
    body = {
        "observations": [
            {
                "observed_on": (START + timedelta(days=i)).isoformat(),
                "quantity": quantity,
            }
            for i in range(days)
        ],
        "horizon_days": 14,
    }
    body.update(extra)
    return body


def test_health_reportsServiceStatus():
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "supplynext-ml"


def test_health_reportsDatabaseUnconfiguredByDefault():
    body = client.get("/health").json()

    assert body["database_configured"] is False
    assert body["database_reachable"] is None


def test_forecastDemand_returnsForecastForValidHistory():
    response = client.post("/api/forecast/demand", json=_payload())

    assert response.status_code == 200
    body = response.json()
    assert len(body["points"]) == 14
    assert body["history_days"] == 40
    assert body["total_forecast_quantity"] > 0


def test_forecastDemand_echoesProductIdentity():
    response = client.post(
        "/api/forecast/demand",
        json=_payload(product_id=42, product_name="Widget"),
    )

    body = response.json()
    assert body["product_id"] == 42
    assert body["product_name"] == "Widget"


def test_forecastDemand_reportsModelComparisonInAutoMode():
    body = client.post("/api/forecast/demand", json=_payload()).json()

    assert body["model_comparison"], "auto mode should show what it compared"
    assert body["model_used"]


def test_forecastDemand_rejectsTooShortHistoryWith422():
    response = client.post("/api/forecast/demand", json=_payload(days=3))

    assert response.status_code == 422
    assert "at least" in response.json()["message"]


def test_forecastDemand_rejectsEmptyObservations():
    response = client.post(
        "/api/forecast/demand", json={"observations": [], "horizon_days": 7}
    )

    assert response.status_code == 422


def test_forecastDemand_rejectsNegativeQuantity():
    response = client.post(
        "/api/forecast/demand",
        json={
            "observations": [{"observed_on": "2026-01-01", "quantity": -5}],
            "horizon_days": 7,
        },
    )

    assert response.status_code == 422


def test_forecastDemand_rejectsHorizonAboveLimit():
    response = client.post("/api/forecast/demand", json=_payload(horizon_days=9999))

    assert response.status_code == 422


def test_reorderPlan_recommendsOrderWhenStockIsLow():
    response = client.post(
        "/api/forecast/reorder-plan",
        json=_payload(current_stock=5, lead_time_days=7),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["should_reorder_now"] is True
    assert body["recommended_order_quantity"] > 0
    assert body["reorder_point"] > 0


def test_reorderPlan_doesNotRecommendOrderWhenStockIsAmple():
    body = client.post(
        "/api/forecast/reorder-plan",
        json=_payload(current_stock=100_000, lead_time_days=7),
    ).json()

    assert body["should_reorder_now"] is False
    assert body["recommended_order_quantity"] == 0


def test_reorderPlan_requiresCurrentStock():
    response = client.post("/api/forecast/reorder-plan", json=_payload())

    assert response.status_code == 422


def test_databaseEndpoint_returns503WhenNoDatabaseConfigured():
    """The DB-backed routes must fail clearly, not with a stack trace."""
    response = client.get("/api/forecast/product/1")

    assert response.status_code == 503
    assert "DATABASE_URL" in response.json()["message"]


def test_openApiDocsAreAvailable():
    assert client.get("/openapi.json").status_code == 200
