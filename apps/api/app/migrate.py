from __future__ import annotations

"""Lightweight schema ensure for SQLite/Postgres without full Alembic yet.

Adds missing tables and common new columns so existing local DBs keep working
after model changes. Production can later switch to Alembic.
"""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .db import Base


# New columns keyed by table name: list of (column_name, sql_type_fragment)
COLUMN_PATCHES: dict[str, list[tuple[str, str]]] = {
    "novels": [
        ("writing_profile", "JSON"),
    ],
    "chapters": [
        ("needs_check", "BOOLEAN DEFAULT 0"),
        ("memory_status", "VARCHAR(24) DEFAULT 'NOT_INDEXED'"),
        ("latest_score", "INTEGER"),
    ],
    "memory_chunks": [
        ("embedding_model_id", "VARCHAR(160)"),
        ("embedding_version", "VARCHAR(80)"),
        ("embedding_dimensions", "INTEGER"),
    ],
    "model_configs": [
        ("top_p", "INTEGER DEFAULT 100"),
        ("context_size", "INTEGER DEFAULT 128000"),
        ("timeout_ms", "INTEGER DEFAULT 120000"),
        ("is_default", "BOOLEAN DEFAULT 0"),
        ("extra_body", "JSON"),
    ],
    "story_events": [("source_outline_node_id", "VARCHAR(36)")],
    "plot_threads": [("source_outline_node_id", "VARCHAR(36)")],
    "story_beats": [("source_outline_node_id", "VARCHAR(36)")],
}


def ensure_schema(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    dialect = engine.dialect.name

    with engine.begin() as conn:
        for table, columns in COLUMN_PATCHES.items():
            if table not in existing_tables:
                continue
            present = {col["name"] for col in inspector.get_columns(table)}
            for name, sql_type in columns:
                if name in present:
                    continue
                conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{name}" {sql_type}'))

    # Ensure new tables (character_states, agent_call_logs, ...) exist.
    Base.metadata.create_all(engine)
    _ = dialect
