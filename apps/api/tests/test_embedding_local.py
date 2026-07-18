from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import get_session
from app.main import app
from app.memory.embeddings import LocalNeuralEmbedding, resolve_embedding
from app.memory.local_runtime import (
    clear_runtime_state,
    is_model_downloaded,
    mark_model_downloaded_for_tests,
    set_encoder_factory,
)
from app.models import ModelConfig
from sqlalchemy import select


class FakeEncoder:
    def __init__(self, dim: int = 8):
        self.dim = dim

    def embed(self, texts):
        for text in texts:
            # deterministic pseudo-vector from text length
            base = float(len(text) + 1)
            yield [base / (i + 1) for i in range(self.dim)]


@pytest.fixture(autouse=True)
def _clean_runtime(tmp_path, monkeypatch):
    clear_runtime_state()
    set_encoder_factory(None)
    # Redirect cache into tmp so tests don't touch real data/
    import app.memory.local_runtime as runtime

    monkeypatch.setattr(runtime, "EMBEDDING_CACHE_DIR", tmp_path / "embeddings")
    yield
    clear_runtime_state()
    set_encoder_factory(None)


def test_local_catalog_lists_three_tiers(session: Session) -> None:
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.get("/api/embedding/local-catalog")
        assert response.status_code == 200
        items = response.json()["items"]
        assert len(items) == 3
        keys = {item["key"] for item in items}
        assert keys == {"bge-small-zh", "jina-base-zh", "e5-large-multi"}
        small = next(i for i in items if i["key"] == "bge-small-zh")
        assert small["recommended"] is True
        assert small["dimensions"] == 512
        assert "MB" in small["sizeLabel"] or "GB" in small["sizeLabel"]
        assert small["downloaded"] is False
        source = response.json().get("downloadSource") or {}
        assert source.get("hfEndpoint")
    finally:
        app.dependency_overrides.clear()


def test_local_download_assigns_embedding_role(session: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    set_encoder_factory(lambda model_id, cache_dir: FakeEncoder(dim=8))

    # Background download commits via db.SessionLocal — bind it to the test engine.
    from sqlalchemy.orm import sessionmaker
    import app.db as db_module

    TestSession = sessionmaker(bind=session.get_bind(), autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", TestSession)

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            started = client.post(
                "/api/novels/starfarer/embedding/local/download",
                json={"catalog_key": "bge-small-zh"},
            )
            assert started.status_code == 200
            body = started.json()
            assert body["state"] in {"downloading", "ready"}
            assert body["catalogKey"] == "bge-small-zh"

            deadline = time.time() + 5
            status = body
            while time.time() < deadline:
                status = client.get("/api/novels/starfarer/embedding/local/status").json()
                if status["state"] in {"ready", "error"}:
                    break
                time.sleep(0.05)

            assert status["state"] == "ready", status
            assert is_model_downloaded("bge-small-zh")

            models = client.get("/api/novels/starfarer/models").json()
            embed_models = [
                m for m in models if "Embedding" in (m.get("roles") or [])
            ]
            assert len(embed_models) == 1
            assert embed_models[0]["provider"] == "内嵌"
            assert embed_models[0]["modelId"] == "BAAI/bge-small-zh-v1.5"
            assert embed_models[0]["status"] == "connected"
            assert embed_models[0]["extraBody"]["catalogKey"] == "bge-small-zh"
    finally:
        app.dependency_overrides.clear()


def test_resolve_embedding_uses_local_neural(session: Session) -> None:
    set_encoder_factory(lambda model_id, cache_dir: FakeEncoder(dim=8))
    mark_model_downloaded_for_tests("bge-small-zh")

    # Clear any prior Embedding roles
    for model in session.scalars(
        select(ModelConfig).where(ModelConfig.novel_id == "starfarer")
    ).all():
        model.roles = [r for r in (model.roles or []) if r != "Embedding"]

    session.add(
        ModelConfig(
            workspace_id="local",
            novel_id="starfarer",
            name="本地 · BGE Small",
            provider="内嵌",
            model_id="BAAI/bge-small-zh-v1.5",
            base_url="",
            status="connected",
            roles=["Embedding"],
            extra_body={
                "runtime": "fastembed",
                "catalogKey": "bge-small-zh",
                "dimensions": 8,
            },
        )
    )
    session.commit()

    provider = resolve_embedding(session, "starfarer")
    assert isinstance(provider, LocalNeuralEmbedding)
    vec = provider.embed_query("信标坠入大气层")
    assert len(vec) == 8
    # L2 normalized
    assert abs(sum(x * x for x in vec) - 1.0) < 1e-5


def test_cloud_embedding_create(session: Session) -> None:
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            # Without reachable endpoint → may be error status but still created
            response = client.post(
                "/api/novels/starfarer/embedding/cloud",
                json={
                    "name": "通义向量",
                    "base_url": "https://example.invalid/v1",
                    "api_key": "sk-test",
                    "model_id": "text-embedding-v3",
                    "provider": "DashScope",
                },
            )
            assert response.status_code == 201
            body = response.json()
            assert body["modelId"] == "text-embedding-v3"
            assert "Embedding" in body["roles"]
            assert body["provider"] == "DashScope"

            models = client.get("/api/novels/starfarer/models").json()
            embed_count = sum(
                1 for m in models if "Embedding" in (m.get("roles") or [])
            )
            assert embed_count == 1

            cleared = client.delete("/api/novels/starfarer/embedding/assignment")
            assert cleared.status_code == 204
            models2 = client.get("/api/novels/starfarer/models").json()
            assert not any("Embedding" in (m.get("roles") or []) for m in models2)
    finally:
        app.dependency_overrides.clear()
