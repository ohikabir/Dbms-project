"""
Optional read-only database access.

Architectural tradeoff, stated plainly: this service reads the SAME PostgreSQL
database that the Spring backend owns, rather than going through the backend's
REST API. That is a deliberate choice with real downsides — two services now
depend on one schema, so a migration in the backend can break this service.

It is done this way because:
  - the access is strictly READ-ONLY (this service never writes),
  - forecasting needs bulk history, and pulling thousands of rows back through
    a paginated REST API would be slow and awkward,
  - it keeps Phase C from requiring any change to the Spring codebase.

If the schema starts churning, the fix is to add a dedicated
"GET /api/analytics/demand-history" endpoint to the Spring backend and switch
the repository layer to call that instead. The repository module is the only
place that would need to change.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import get_settings

_engine: Engine | None = None


def get_engine() -> Engine | None:
    """Lazily create the shared engine. Returns None when no DB is configured."""
    global _engine
    settings = get_settings()

    if not settings.database_configured:
        return None

    if _engine is None:
        _engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,  # silently reconnect after the DB restarts
            future=True,
        )
    return _engine


def database_reachable() -> bool | None:
    """None when unconfigured, True/False when configured. Used by /health."""
    engine = get_engine()
    if engine is None:
        return None
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - health check must never raise
        return False


def connection_scope() -> Iterator:
    """Yield a connection, raising a clear error when the DB is not configured."""
    engine = get_engine()
    if engine is None:
        raise RuntimeError(
            "No database configured. Set DATABASE_URL to use database-backed "
            "endpoints, or use the stateless POST /api/forecast/demand endpoint."
        )
    with engine.connect() as connection:
        yield connection
