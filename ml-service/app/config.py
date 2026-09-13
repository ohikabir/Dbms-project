"""Runtime configuration, read from environment variables (or a .env file)."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "supplynext-ml"
    version: str = "1.0.0"

    # Left empty by default on purpose: every stateless endpoint works without
    # a database, so the service starts and is useful even with no DB access.
    # Set it to enable the /api/forecast/product/... endpoints.
    #   postgresql+psycopg2://postgres:1234@localhost:5432/scm_db
    database_url: str = ""

    # Demand is only counted from sales orders in this status, matching the
    # Spring backend's AnalyticsService.computeDemandStats(). Keep the two in
    # sync — if they disagree, EOQ and the forecast will quietly contradict
    # each other.
    demand_order_status: str = "SHIPPED"

    default_horizon_days: int = 30
    default_service_level: float = 0.95
    default_lead_time_days: int = 7

    # Frontend origin allowed to call this service directly.
    cors_allowed_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
