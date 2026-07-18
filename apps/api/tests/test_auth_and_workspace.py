from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.auth import set_workspace_id
from app.db import Base, get_session
from app.main import app
from app.repositories import SqlAlchemyRepository
from app.seed import ensure_seed_data


@pytest.fixture()
def client() -> TestClient:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def _session():
        with TestingSession() as session:
            ensure_seed_data(session, demo=True)
            yield session

    app.dependency_overrides[get_session] = _session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)


def test_auth_status_dev_open(client: TestClient) -> None:
    res = client.get("/api/auth/status")
    assert res.status_code == 200
    body = res.json()
    assert body["workspaceId"] == "local"
    assert body["mode"] in {"dev", "api_key"}


def test_workspace_isolation_on_repository(session: Session) -> None:
    set_workspace_id("local")
    repo = SqlAlchemyRepository(session, workspace_id="local")
    novel = repo.get_novel("starfarer")
    assert novel.id == "starfarer"

    set_workspace_id("other")
    other = SqlAlchemyRepository(session, workspace_id="other")
    with pytest.raises(Exception) as exc:
        other.get_novel("starfarer")
    assert "404" in str(exc.value.status_code) or "not found" in str(exc.value.detail).lower()
    set_workspace_id("local")


def test_list_novels_scoped(client: TestClient) -> None:
    res = client.get("/api/novels")
    assert res.status_code == 200
    ids = {item["id"] for item in res.json()}
    assert "starfarer" in ids


def test_idempotent_generate_returns_same_job(session: Session) -> None:
    from app.models import Chapter
    from app.services import GenerationService

    set_workspace_id("local")
    chapter = session.get(Chapter, "c1")
    assert chapter is not None
    service = GenerationService(session)
    a = service.create_job(
        chapter, chapter.current_version_id, "GENERATE_CHAPTER", options={"target_words": 1000}
    )
    b = service.create_job(
        chapter, chapter.current_version_id, "GENERATE_CHAPTER", options={"target_words": 1000}
    )
    assert a.id == b.id
