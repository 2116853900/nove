from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import get_session
from app.main import app


def test_project_and_story_contracts(session: Session) -> None:
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            novels = client.get("/api/novels")
            chapters = client.get("/api/novels/starfarer/chapters")
            outline = client.get("/api/novels/starfarer/outline")
            characters = client.get("/api/novels/starfarer/characters")

        assert novels.status_code == 200
        assert novels.json()[0]["title"] == "星河旅人"
        assert chapters.json()[0]["currentVersionId"]
        assert outline.json()[0]["kind"] == "volume"
        assert characters.json()[0]["name"]
    finally:
        app.dependency_overrides.clear()


def test_create_novel_starts_with_empty_outline(session: Session) -> None:
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            library = client.get("/api/models")
            assert library.status_code == 200
            # Seed a workspace model if empty (tests use demo seed with novel-scoped only)
            if not library.json():
                created_lib = client.post(
                    "/api/models",
                    json={
                        "name": "Workspace Draft",
                        "provider": "OpenAI 兼容",
                        "model_id": "workspace-test",
                        "base_url": "https://cloud.test.invalid/v1",
                        "is_default": True,
                    },
                )
                assert created_lib.status_code == 201
                default_id = created_lib.json()["id"]
            else:
                default_id = library.json()[0]["id"]

            response = client.post(
                "/api/novels",
                json={
                    "title": "测试新书",
                    "genre": "悬疑",
                    "core_idea": "一封寄给未来的信。",
                    "planned_chapters": 30,
                    "default_model_id": default_id,
                    "write_model_id": default_id,
                    "audit_model_id": default_id,
                    "plan_model_id": default_id,
                },
            )
            assert response.status_code == 201
            novel_id = response.json()["id"]
            chapters = client.get(f"/api/novels/{novel_id}/chapters")
            outline = client.get(f"/api/novels/{novel_id}/outline")
            models = client.get(f"/api/novels/{novel_id}/models")
        assert chapters.status_code == 200
        assert chapters.json() == []
        assert outline.status_code == 200
        assert outline.json() == []
        assert models.status_code == 200
        assert len(models.json()) >= 1
        assert any("写作" in (m.get("roles") or []) for m in models.json())
    finally:
        app.dependency_overrides.clear()


def test_story_crud_and_model_secrets_contract(session: Session) -> None:
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            chapter = client.post(
                "/api/novels/starfarer/chapters",
                json={"title": "新的航线", "brief": {"goal": "改变航向"}},
            )
            character = client.post(
                "/api/novels/starfarer/characters",
                json={"name": "测试人物", "data": {"role": "配角"}},
            )
            model = client.post(
                "/api/novels/starfarer/models",
                json={
                    "name": "测试模型",
                    "provider": "OpenAI 兼容",
                    "model_id": "test-model",
                    "base_url": "https://cloud.test.invalid/v1",
                    "api_key": "secret-key",
                    "roles": ["写作"],
                },
            )
            local_probe = client.post(
                "/api/models/probe",
                json={
                    "provider": "本地",
                    "model_id": "nove-local",
                    "base_url": "",
                    "api_key": "",
                },
            )

        assert chapter.status_code == 201
        assert chapter.json()["index"] == 14
        assert character.status_code == 201
        assert model.status_code == 201
        assert model.json()["apiKeyMasked"] == "********"
        assert "secret-key" not in str(model.json())
        assert local_probe.status_code == 422
        assert "云端" in str(local_probe.json()["detail"])
    finally:
        app.dependency_overrides.clear()


def test_generation_accept_confirm_and_memory_contract(session: Session, monkeypatch) -> None:
    from app.services import GenerationService

    monkeypatch.setattr("app.routes.run_generation", lambda *_: None)
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            before = client.get("/api/chapters/c12").json()
            created = client.post(
                "/api/chapters/c12/generate",
                json={
                    "base_version_id": before["currentVersionId"],
                    "target_words": 1000,
                    "goal": "推动新的冲突",
                    "auto_audit": True,
                },
            )
            assert created.status_code == 202
            job = created.json()
            GenerationService(session).run_job(job["id"], auto_audit=True)
            events = client.get(f"/api/jobs/{job['id']}/events")
            assert events.status_code == 200
            assert "event: completed" in events.text
            completed = client.get(f"/api/jobs/{job['id']}").json()
            version_id = completed["result"]["versionId"]

            unchanged = client.get("/api/chapters/c12").json()
            assert unchanged["currentVersionId"] is None
            accepted = client.post(f"/api/chapters/c12/versions/{version_id}/accept")
            assert accepted.status_code == 200
            assert accepted.json()["currentVersionId"] == version_id

            blocked = client.post("/api/chapters/c12/confirm", json={})
            assert blocked.status_code == 409
            confirmed = client.post(
                "/api/chapters/c12/confirm",
                json={"gate_override_reason": "API 合同测试确认继续使用当前版本"},
            )
            assert confirmed.status_code == 200
            assert confirmed.json()["memoryStatus"] == "INDEXED"
            confirmed_again = client.post("/api/chapters/c12/confirm", json={})
            assert confirmed_again.status_code == 200
            assert confirmed_again.json()["confirmedVersionId"] == version_id
    finally:
        app.dependency_overrides.clear()


def test_audit_candidate_version_without_current(session: Session) -> None:
    """AI candidates can be audited before they become the current version."""
    from app.models import Chapter
    from app.services import ChapterService

    chapter = session.get(Chapter, "c12")
    assert chapter is not None
    chapter.current_version_id = None
    session.commit()

    candidate = ChapterService(session).create_version(
        chapter,
        content="候选正文用于审计接口测试。" * 40,
        title=chapter.title,
        source="generate",
        base_version_id=None,
        make_current=False,
    )
    assert chapter.current_version_id is None

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            empty = client.post(f"/api/chapters/{chapter.id}/audit", json={})
            assert empty.status_code == 409
            assert "没有正文" in empty.json()["detail"]

            by_path = client.post(
                f"/api/chapters/{chapter.id}/versions/{candidate.id}/audit"
            )
            assert by_path.status_code == 200
            body = by_path.json()
            assert body["versionId"] == candidate.id
            assert body["chapterId"] == chapter.id

            by_body = client.post(
                f"/api/chapters/{chapter.id}/audit",
                json={"version_id": candidate.id},
            )
            assert by_body.status_code == 200
            assert by_body.json()["versionId"] == candidate.id

            # Candidate audit must not invent a current version.
            after = client.get(f"/api/chapters/{chapter.id}").json()
            assert after["currentVersionId"] is None
    finally:
        app.dependency_overrides.clear()


def test_restore_and_delete_version_contract(session: Session) -> None:
    from app.models import Chapter, ChapterVersion
    from app.services import ChapterService

    chapter = session.get(Chapter, "c1")
    assert chapter is not None and chapter.current_version_id
    previous_id = chapter.current_version_id
    candidate = ChapterService(session).create_version(
        chapter,
        content="用于恢复与删除接口测试的候选正文" * 60,
        title=chapter.title,
        source="rewrite",
        base_version_id=previous_id,
        make_current=False,
    )

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            before = client.get(f"/api/chapters/{chapter.id}/versions").json()
            restored = client.post(
                f"/api/chapters/{chapter.id}/versions/{candidate.id}/restore",
                json={"current_content": None},
            )
            after_restore = client.get(f"/api/chapters/{chapter.id}/versions").json()
            deleted = client.delete(
                f"/api/chapters/{chapter.id}/versions/{previous_id}"
            )
            after_delete = client.get(f"/api/chapters/{chapter.id}/versions").json()
            delete_current = client.delete(
                f"/api/chapters/{chapter.id}/versions/{candidate.id}"
            )

        assert restored.status_code == 200
        assert restored.json()["chapter"]["currentVersionId"] == candidate.id
        assert len(after_restore) == len(before)
        assert deleted.status_code == 204
        assert all(item["id"] != previous_id for item in after_delete)
        assert delete_current.status_code == 409
        assert session.get(ChapterVersion, candidate.id) is not None
    finally:
        app.dependency_overrides.clear()


def test_delete_novel_cascades_owned_data(session: Session) -> None:
    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            created = client.post("/api/novels", json={"title": "待删除项目"})
            novel_id = created.json()["id"]
            deleted = client.delete(f"/api/novels/{novel_id}")
            missing = client.get(f"/api/novels/{novel_id}")
        assert deleted.status_code == 204
        assert missing.status_code == 404
    finally:
        app.dependency_overrides.clear()
