"""Phase 1 smoke test for core-api config and DB wiring (no live DB required)."""

from __future__ import annotations

from kata_core_api.config import Settings, get_settings


def test_settings_defaults_to_local_postgres() -> None:
    settings = get_settings()
    assert isinstance(settings, Settings)
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_env_prefix_override(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("KATA_DATABASE_URL", "postgresql+psycopg://u:p@db:5432/x")
    assert Settings().database_url.endswith("/x")
