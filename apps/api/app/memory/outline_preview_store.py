"""Database-backed TTL store for outline generation previews."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import OutlinePreview, utcnow

_TTL_SECONDS = 30 * 60


def _purge_expired(session: Session) -> None:
    session.execute(delete(OutlinePreview).where(OutlinePreview.expires_at < utcnow()))


def _record(row: OutlinePreview) -> dict[str, Any]:
    record = dict(row.payload or {})
    record["previewId"] = row.id
    record["novelId"] = row.novel_id
    record["expiresAt"] = row.expires_at.timestamp()
    return record


def put_preview(
    session: Session,
    *,
    novel_id: str,
    parent_id: str | None,
    child_kind: str,
    create_chapters: bool,
    nodes: list[dict[str, Any]],
    source: str,
    coherence: dict[str, Any] | None = None,
    mode: str = "children",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _purge_expired(session)
    preview_id = uuid4().hex
    normalized = []
    for item in nodes:
        node = dict(item)
        node.setdefault("selected", True)
        normalized.append(node)
    now = utcnow()
    row = OutlinePreview(
        id=preview_id,
        novel_id=novel_id,
        expires_at=now + timedelta(seconds=_TTL_SECONDS),
        payload={
            "parentId": parent_id,
            "childKind": child_kind,
            "createChapters": create_chapters,
            "nodes": normalized,
            "source": source,
            "coherence": coherence or {},
            "mode": mode,
            "meta": meta or {},
            "createdAt": now.timestamp(),
        },
    )
    session.add(row)
    session.commit()
    return _record(row)


def get_preview(session: Session, preview_id: str, *, novel_id: str | None = None) -> dict[str, Any] | None:
    _purge_expired(session)
    row = session.get(OutlinePreview, preview_id)
    if row is None or (novel_id and row.novel_id != novel_id):
        return None
    return _record(row)


def update_preview_nodes(
    session: Session,
    preview_id: str,
    nodes: list[dict[str, Any]],
    *,
    novel_id: str | None = None,
) -> dict[str, Any] | None:
    _purge_expired(session)
    row = session.get(OutlinePreview, preview_id)
    if row is None or (novel_id and row.novel_id != novel_id):
        return None
    payload = dict(row.payload or {})
    payload["nodes"] = [dict(node) for node in nodes]
    row.payload = payload
    row.expires_at = utcnow() + timedelta(seconds=_TTL_SECONDS)
    session.commit()
    return _record(row)


def pop_preview(session: Session, preview_id: str, *, novel_id: str | None = None) -> dict[str, Any] | None:
    _purge_expired(session)
    row = session.get(OutlinePreview, preview_id)
    if row is None or (novel_id and row.novel_id != novel_id):
        return None
    record = _record(row)
    session.delete(row)
    session.commit()
    return record


def clear_all(session: Session) -> None:
    session.execute(delete(OutlinePreview))
    session.commit()
