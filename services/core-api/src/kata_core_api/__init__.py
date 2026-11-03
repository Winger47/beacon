"""Kata core-api service.

Owns the `core` schema: domain CRUD, RBAC, triage workflows and queries. The HTTP
layer (FastAPI) arrives in Phase 1 Week 3; Week 1 establishes config, the DB session
factory and Alembic migrations.
"""

__version__ = "0.0.0"
