"""core-api configuration, loaded from environment variables (12-factor)."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KATA_", env_file=".env", extra="ignore")

    # Default matches the local `core` compose profile (deploy/compose).
    database_url: str = Field(
        default="postgresql+psycopg://kata:kata@localhost:5432/kata",
        description="SQLAlchemy URL for the primary PostgreSQL cluster.",
    )
    sql_echo: bool = Field(default=False, description="Echo SQL for debugging.")


def get_settings() -> Settings:
    return Settings()
