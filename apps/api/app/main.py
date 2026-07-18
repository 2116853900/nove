from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from .agents import ensure_default_skills
from .config import settings
from .db import SessionLocal, engine
from .logging_utils import configure_logging, set_trace_id
from .memory.pgvector_store import ensure_pgvector, pgvector_status
from .memory.qdrant_store import qdrant_status
from .migrate import ensure_schema
from .routes import router
from .seed import ensure_seed_data


class TraceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        incoming = request.headers.get("x-trace-id") or request.headers.get("x-request-id")
        tid = set_trace_id(incoming)
        response = await call_next(request)
        response.headers["X-Trace-Id"] = tid
        return response


@asynccontextmanager
async def lifespan(_: FastAPI):
    configure_logging(settings.log_level)
    # Default embedding downloads to CN HF mirror (hf-mirror.com) unless overridden.
    from .memory.download_source import ensure_cn_download_endpoint

    ensure_cn_download_endpoint()
    ensure_schema(engine)
    if settings.enable_pgvector:
        ensure_pgvector(engine)
    with SessionLocal() as session:
        ensure_seed_data(session)
        ensure_default_skills(session)
    yield


app = FastAPI(
    title="Nove API",
    version="0.1.0",
    description="Backend for the Nove long-form fiction writing workspace.",
    lifespan=lifespan,
)
app.add_middleware(TraceMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/health")
def health():
    with SessionLocal() as session:
        vector_database = qdrant_status(session)
    return {
        "status": "ok",
        "env": settings.app_env,
        "database": "postgres" if settings.database_url.startswith("postgresql") else "sqlite",
        "pgvector": pgvector_status(engine),
        "vectorDatabase": vector_database,
    }
