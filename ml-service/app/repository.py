"""
Read-only queries against the SupplyNext schema.

Table and column names follow Hibernate's default snake_case mapping of the
backend's JPA entities (SalesOrderItem -> sales_order_item, and so on). The
one exception is the User entity, which the backend maps explicitly to
"app_user" because "user" is reserved in PostgreSQL — this module does not
touch it.

Every query here is a SELECT. Nothing in this service writes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import text

from .config import get_settings
from .database import get_engine
from .forecasting import Observation


@dataclass
class ProductRow:
    id: int
    sku: str
    name: str
    unit_cost: float | None
    supplier_id: int | None
    supplier_name: str | None
    lead_time_days: int | None


class DatabaseNotConfiguredError(RuntimeError):
    pass


def _engine_or_raise():
    engine = get_engine()
    if engine is None:
        raise DatabaseNotConfiguredError(
            "No database configured. Set DATABASE_URL to use this endpoint, or "
            "POST history directly to /api/forecast/demand instead."
        )
    return engine


def fetch_products() -> list[ProductRow]:
    """All products, with their supplier's lead time joined in."""
    sql = text(
        """
        SELECT p.id, p.sku, p.name, p.unit_cost,
               s.id AS supplier_id, s.name AS supplier_name, s.lead_time_days
        FROM product p
        LEFT JOIN supplier s ON s.id = p.supplier_id
        ORDER BY p.id
        """
    )
    with _engine_or_raise().connect() as connection:
        rows = connection.execute(sql).mappings().all()

    return [
        ProductRow(
            id=r["id"],
            sku=r["sku"],
            name=r["name"],
            unit_cost=r["unit_cost"],
            supplier_id=r["supplier_id"],
            supplier_name=r["supplier_name"],
            lead_time_days=r["lead_time_days"],
        )
        for r in rows
    ]


def fetch_product(product_id: int) -> ProductRow | None:
    sql = text(
        """
        SELECT p.id, p.sku, p.name, p.unit_cost,
               s.id AS supplier_id, s.name AS supplier_name, s.lead_time_days
        FROM product p
        LEFT JOIN supplier s ON s.id = p.supplier_id
        WHERE p.id = :product_id
        """
    )
    with _engine_or_raise().connect() as connection:
        row = connection.execute(sql, {"product_id": product_id}).mappings().first()

    if row is None:
        return None
    return ProductRow(
        id=row["id"],
        sku=row["sku"],
        name=row["name"],
        unit_cost=row["unit_cost"],
        supplier_id=row["supplier_id"],
        supplier_name=row["supplier_name"],
        lead_time_days=row["lead_time_days"],
    )


def fetch_demand_history(product_id: int) -> list[Observation]:
    """
    Daily shipped quantity for one product.

    Only SHIPPED sales orders count as demand, matching the Spring backend's
    AnalyticsService.computeDemandStats(). A PENDING order is a request, not a
    fulfilled sale, and counting it would inflate the forecast.
    """
    sql = text(
        """
        SELECT so.order_date AS observed_on, SUM(soi.quantity) AS quantity
        FROM sales_order_item soi
        JOIN sales_order so ON so.id = soi.sales_order_id
        WHERE soi.product_id = :product_id
          AND so.status = :status
          AND so.order_date IS NOT NULL
        GROUP BY so.order_date
        ORDER BY so.order_date
        """
    )
    params = {"product_id": product_id, "status": get_settings().demand_order_status}
    with _engine_or_raise().connect() as connection:
        rows = connection.execute(sql, params).mappings().all()

    return [
        Observation(observed_on=r["observed_on"], quantity=float(r["quantity"] or 0))
        for r in rows
    ]


def fetch_demand_history_bulk() -> dict[int, list[Observation]]:
    """
    Demand history for every product in ONE query.

    The per-product query above is fine for a single forecast, but running it
    in a loop over N products is the classic N+1 problem. The "forecast every
    product" endpoint uses this instead.
    """
    sql = text(
        """
        SELECT soi.product_id, so.order_date AS observed_on,
               SUM(soi.quantity) AS quantity
        FROM sales_order_item soi
        JOIN sales_order so ON so.id = soi.sales_order_id
        WHERE so.status = :status
          AND so.order_date IS NOT NULL
        GROUP BY soi.product_id, so.order_date
        ORDER BY soi.product_id, so.order_date
        """
    )
    with _engine_or_raise().connect() as connection:
        rows = connection.execute(sql, {"status": get_settings().demand_order_status}).mappings().all()

    history: dict[int, list[Observation]] = {}
    for row in rows:
        history.setdefault(row["product_id"], []).append(
            Observation(observed_on=row["observed_on"], quantity=float(row["quantity"] or 0))
        )
    return history


def fetch_total_stock(product_id: int) -> float:
    """Units on hand for a product, summed across every warehouse."""
    sql = text(
        "SELECT COALESCE(SUM(quantity), 0) AS total FROM inventory WHERE product_id = :product_id"
    )
    with _engine_or_raise().connect() as connection:
        row = connection.execute(sql, {"product_id": product_id}).mappings().first()
    return float(row["total"]) if row else 0.0


def fetch_latest_order_date() -> date | None:
    """
    The most recent shipped order date in the whole system.

    Used as the series end date so a product that stopped selling two months
    ago shows two months of zeros rather than a series that simply stops — the
    difference between "no data" and "no demand".
    """
    sql = text(
        "SELECT MAX(order_date) AS latest FROM sales_order WHERE status = :status"
    )
    with _engine_or_raise().connect() as connection:
        row = connection.execute(sql, {"status": get_settings().demand_order_status}).mappings().first()
    return row["latest"] if row and row["latest"] else None
