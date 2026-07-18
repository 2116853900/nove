from __future__ import annotations

"""Optional pgvector helpers for PostgreSQL deployments.

Default path stores embeddings in MemoryChunk.metadata_json (SQLite-friendly).
When DATABASE_URL is PostgreSQL and pgvector extension is available, callers
may use ensure_pgvector() once at startup; hybrid retrieval still works via
JSON vectors so behavior stays consistent without the extension.
"""

import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

logger = logging.getLogger("nove.pgvector")


def is_postgres(engine: Engine) -> bool:
    return engine.dialect.name == "postgresql"


def ensure_pgvector(engine: Engine) -> dict[str, Any]:
    """Try to CREATE EXTENSION vector. Non-fatal if unavailable."""
    if not is_postgres(engine):
        return {"enabled": False, "reason": "not_postgres"}
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        logger.info("pgvector extension ready")
        return {"enabled": True, "reason": "ok"}
    except Exception as exc:
        logger.warning("pgvector unavailable, using JSON embeddings: %s", exc)
        return {"enabled": False, "reason": str(exc)}


def pgvector_status(engine: Engine) -> dict[str, Any]:
    if not is_postgres(engine):
        return {"dialect": engine.dialect.name, "pgvector": False}
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            ).first()
        return {"dialect": "postgresql", "pgvector": bool(row)}
    except Exception as exc:
        return {"dialect": "postgresql", "pgvector": False, "error": str(exc)}
