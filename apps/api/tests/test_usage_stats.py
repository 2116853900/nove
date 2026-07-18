from __future__ import annotations

from sqlalchemy.orm import Session

from app.auth import set_workspace_id
from app.models import AgentCallLog, new_id
from app.observability import track_agent_call


def test_usage_aggregation_endpoint_shape(session: Session) -> None:
    set_workspace_id("local")
    with track_agent_call(
        session,
        novel_id="starfarer",
        chapter_id="c1",
        agent_name="Writer",
        model_name="demo-model",
        operation="generate",
        input_summary="t",
    ) as meta:
        meta["input_tokens"] = 100
        meta["output_tokens"] = 50
        meta["output_summary"] = "ok"

    # Direct insert second row
    session.add(
        AgentCallLog(
            id=new_id(),
            workspace_id="local",
            novel_id="starfarer",
            agent_name="Auditor",
            model_name="demo-model",
            operation="audit",
            status="ok",
            duration_ms=12,
            input_tokens=20,
            output_tokens=10,
        )
    )
    session.commit()

    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool

    from app.db import Base, get_session
    from app.main import app
    from app.seed import ensure_seed_data

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _session():
        with TestingSession() as db:
            ensure_seed_data(db, demo=True)
            with track_agent_call(
                db,
                novel_id="starfarer",
                chapter_id="c1",
                agent_name="Writer",
                model_name="m1",
                operation="gen",
            ) as meta:
                meta["input_tokens"] = 10
                meta["output_tokens"] = 5
            yield db

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as client:
        res = client.get("/api/novels/starfarer/usage")
        assert res.status_code == 200
        body = res.json()
        assert body["calls"] >= 1
        assert "byModel" in body
        assert "byAgent" in body
        assert "estimatedCostUsd" in body
    app.dependency_overrides.clear()
