from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


API_ROOT = Path(__file__).resolve().parents[1]

_DEV_ENCRYPTION_DEFAULT = "nove-local-development-key"


def _load_settings() -> "Settings":
    app_env = os.getenv("APP_ENV", "development").lower()
    is_production = app_env in {"production", "prod"}

    encryption_key = os.getenv("ENCRYPTION_KEY")
    secret_key = os.getenv("SECRET_KEY")
    api_key = os.getenv("API_KEY", "").strip()

    if is_production:
        missing = []
        if not encryption_key or encryption_key == _DEV_ENCRYPTION_DEFAULT:
            missing.append("ENCRYPTION_KEY")
        if not secret_key:
            missing.append("SECRET_KEY")
        if not api_key:
            missing.append("API_KEY")
        if missing:
            sys.stderr.write(
                "FATAL: production requires "
                + ", ".join(missing)
                + ". Refusing to start with insecure defaults.\n"
            )
            raise SystemExit(2)
    else:
        encryption_key = encryption_key or _DEV_ENCRYPTION_DEFAULT
        secret_key = secret_key or "nove-dev-secret"

    return Settings(
        app_env=app_env,
        is_production=is_production,
        database_url=os.getenv(
            "DATABASE_URL", f"sqlite:///{(API_ROOT / 'data' / 'nove.db').as_posix()}"
        ),
        cors_origins=tuple(
            item.strip()
            for item in os.getenv(
                "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
            ).split(",")
            if item.strip()
        ),
        encryption_key=encryption_key,
        secret_key=secret_key,
        api_key=api_key,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        enable_pgvector=os.getenv("ENABLE_PGVECTOR", "1") not in {"0", "false", "False"},
        max_concurrent_jobs=int(os.getenv("MAX_CONCURRENT_JOBS", "2")),
        qdrant_url=os.getenv("QDRANT_URL", "").strip(),
        qdrant_api_key=os.getenv("QDRANT_API_KEY", "").strip(),
        qdrant_collection_prefix=(
            os.getenv("QDRANT_COLLECTION_PREFIX", "nove_memory").strip()
            or "nove_memory"
        ),
        # Embedding weight mirror (huggingface_hub HF_ENDPOINT). Default CN mirror.
        embedding_hf_endpoint=(
            os.getenv("EMBEDDING_HF_ENDPOINT")
            or os.getenv("HF_ENDPOINT")
            or "https://hf-mirror.com"
        ).rstrip("/"),
    )


@dataclass(frozen=True)
class Settings:
    app_env: str
    is_production: bool
    database_url: str
    cors_origins: tuple[str, ...]
    encryption_key: str
    secret_key: str
    api_key: str
    log_level: str
    enable_pgvector: bool
    max_concurrent_jobs: int
    qdrant_url: str
    qdrant_api_key: str
    qdrant_collection_prefix: str
    embedding_hf_endpoint: str


settings = _load_settings()
