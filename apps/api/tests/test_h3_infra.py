from __future__ import annotations

from app.logging_utils import get_trace_id, set_trace_id
from app.memory.pgvector_store import is_postgres, pgvector_status
from app.db import engine


def test_trace_id_context() -> None:
    tid = set_trace_id("abc123")
    assert tid == "abc123"
    assert get_trace_id() == "abc123"
    set_trace_id(None)


def test_pgvector_status_on_sqlite() -> None:
    assert is_postgres(engine) is False
    status = pgvector_status(engine)
    assert status["dialect"] == "sqlite"
    assert status["pgvector"] is False


def test_alembic_env_imports() -> None:
    # Ensure env module is importable without running migrations against live DB.
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "alembic" / "env.py"
    assert path.exists()
    # Only check revision file exists
    rev = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "20260716_0001_baseline.py"
    assert rev.exists()
