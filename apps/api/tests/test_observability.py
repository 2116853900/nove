from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.migrate import ensure_schema
from app.models import AgentCallLog
from app.observability import track_agent_call
from app.db import engine


def test_ensure_schema_idempotent() -> None:
    ensure_schema(engine)
    ensure_schema(engine)


def test_track_agent_call_writes_log(session: Session) -> None:
    with track_agent_call(
        session,
        novel_id="starfarer",
        chapter_id="c1",
        agent_name="Writer",
        model_name="test-model",
        operation="unit",
        input_summary="hello",
    ) as meta:
        meta["output_summary"] = "world"
        meta["input_tokens"] = 3
        meta["output_tokens"] = 5

    rows = session.scalars(
        select(AgentCallLog).where(AgentCallLog.novel_id == "starfarer")
    ).all()
    assert rows
    assert rows[-1].agent_name == "Writer"
    assert rows[-1].status == "ok"
    assert rows[-1].duration_ms >= 0
