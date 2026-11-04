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

    # Synchronous import path (Phase 2) is for SMALL files only. The streaming ingestion
    # plane (gateway → Kafka → reconciler) handles large uploads in Phase 4.
    import_max_bytes: int = Field(
        default=10 * 1024 * 1024,
        description="Hard cap on a synchronous /import upload. Larger reports are rejected 413.",
    )

    # OIDC / Keycloak. JWKS is fetched and cached from the issuer.
    oidc_jwks_url: str = Field(
        default="http://localhost:8080/realms/kata/protocol/openid-connect/certs"
    )
    oidc_issuer: str = Field(default="http://localhost:8080/realms/kata")
    oidc_audience: str = Field(default="kata-core-api")

    # CORS origins for the SPA dev server (comma-separated via env KATA_CORS_ORIGINS).
    cors_origins: list[str] = Field(default=["http://localhost:5173"])

    # Dev auth: trust an X-Kata-Dev-User header (local only). NEVER enable in production.
    dev_auth: bool = Field(default=False)
    # Global role granted to dev-header users (local convenience so dev can exercise writes).
    dev_auth_global_role: str | None = Field(default="owner")


def get_settings() -> Settings:
    return Settings()
