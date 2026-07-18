from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from sqlalchemy.orm import Session

from .models import AgentCallLog, new_id


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def track_agent_call(
    session: Session | None,
    *,
    novel_id: str | None,
    chapter_id: str | None,
    agent_name: str,
    model_name: str | None = None,
    operation: str = "",
    input_summary: str = "",
) -> Iterator[dict[str, Any]]:
    """Record duration/status of an agent-style call. Safe if session is None."""
    started = time.perf_counter()
    meta: dict[str, Any] = {
        "input_tokens": None,
        "output_tokens": None,
        "output_summary": "",
        "error": None,
        "status": "ok",
    }
    try:
        yield meta
    except Exception as exc:
        meta["status"] = "error"
        meta["error"] = str(exc)
        raise
    finally:
        if session is None:
            return
        duration_ms = int((time.perf_counter() - started) * 1000)
        try:
            session.add(
                AgentCallLog(
                    id=new_id(),
                    workspace_id="local",
                    novel_id=novel_id or "",
                    chapter_id=chapter_id,
                    agent_name=agent_name,
                    model_name=model_name or "",
                    operation=operation,
                    status=str(meta.get("status") or "ok"),
                    duration_ms=duration_ms,
                    input_tokens=meta.get("input_tokens"),
                    output_tokens=meta.get("output_tokens"),
                    input_summary=(input_summary or "")[:500],
                    output_summary=str(meta.get("output_summary") or "")[:500],
                    error=meta.get("error"),
                    metadata_json={
                        "at": utc_iso(),
                    },
                )
            )
            session.commit()
        except Exception:
            try:
                session.rollback()
            except Exception:
                pass


def summarize_json(data: Any, limit: int = 400) -> str:
    try:
        text = json.dumps(data, ensure_ascii=False)
    except Exception:
        text = str(data)
    return text[:limit]
