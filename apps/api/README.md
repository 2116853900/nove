# Nove API

FastAPI backend for the Nove writing workspace. The default development
database is SQLite so the complete product can run without infrastructure.
Set `DATABASE_URL` to a PostgreSQL URL for a production-style deployment.

Writing pipeline uses **AgentScope 2.x** agents when remote models are
configured:

- Plot（大纲/写作）→ scene beats
- Writer（写作）→ chapter draft
- Continuity skill（白名单）→ hard continuity check + `skill_runs` log
- Auditor（审计/连续性）→ structured scoring JSON
- Memory（提取/审计）on confirm → fact delta → events / entities / plot threads

Without remote models, local template writing + heuristic plot/memory/audit
remain available so the product still runs offline.

Memory / RAG:

- Confirm embeds chunks and stores vectors in Qdrant (persistent Local Mode by default,
  `QDRANT_URL` service mode in Docker/production). SQLite/Postgres retains chunk text and metadata only.
- Every chapter generation, continuation, rewrite, audit rewrite, audit, and selection edit
  assembles volume/arc/chapter outline, recent confirmed chapters, Qdrant RAG, entities,
  plot threads, character states, and location states.
- Qdrant performs semantic candidate search; the application re-ranks with entity,
  plotline, time-proximity, and importance scores.
- Re-confirm marks later chapters `OUTDATED` / `needs_check` and returns `impact`.
- `GET /api/novels/{id}/memory/status` · `POST /api/novels/{id}/memory/reindex`
- `GET /api/novels/{id}/impact/{chapter_id}`
- `POST /api/chapters/{id}/selection-edit` — expand/shrink/rewrite/dialogue/style candidate (does not auto-write)
- `POST /api/novels/{id}/outline/generate` — append volume/arc/chapter/scene children (locked siblings untouched)
- `GET /api/novels/{id}/character-states` · `location-states` · `GET /api/story-entities/{id}/states`
- `GET /api/novels/{id}/agent-calls` — agent call latency/status summaries
- `POST /api/outline-nodes/{id}/move` — up/down + renumber chapters
- `GET /api/chapters/{id}/versions/diff?left=&right=` — paragraph diff
- `POST /api/novels/import` — split TXT/MD into chapters
- `GET /api/novels/{id}/export?format=markdown|txt|json`
- `GET /api/novels/{id}/relations` · `PUT /api/story-entities/{id}/relations`
- `POST /api/novels/{id}/audit-scan` — whole-novel continuity scan
- `GET /api/novels/{id}/usage` — token / latency / cost estimate by model & agent

### Schema / ops

```powershell
# Dev: auto ensure_schema on startup
python -m uvicorn app.main:app --reload --port 8000

# Optional formal migrations (fresh / production)
alembic upgrade head

# Postgres + Qdrant (compose)
# set DATABASE_URL=postgresql+psycopg://nove:nove@localhost:5432/nove
# set QDRANT_URL=http://localhost:6333
```

Responses include `X-Trace-Id`. Logs are JSON lines (`LOG_LEVEL`).

### Security

```powershell
# Development: open API (no key)
# Production (required):
$env:APP_ENV="production"
$env:API_KEY="your-long-random-key"
$env:ENCRYPTION_KEY="your-encryption-secret"
$env:SECRET_KEY="your-app-secret"
$env:MAX_CONCURRENT_JOBS="2"
```

Clients send `X-API-Key` (web: `VITE_API_KEY` or `localStorage['nove:api-key']`).  
All repository lookups filter by `workspace_id`.

```powershell
cd apps/api
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

OpenAPI is available at `http://127.0.0.1:8000/docs`. On first startup the
database is created with an empty local workspace (no demo novel).
