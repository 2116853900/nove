from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.craft import normalize_writing_profile, profile_readiness
from app.db import get_session
from app.main import app
from app.models import Chapter, ModelConfig, Novel, NovelRule, OutlineNode, StoryEntity
from app.services_bible_bootstrap import BibleBootstrapService
from app.services_blueprint import BlueprintService
from app.services_bootstrap import NovelBootstrapService


def _novel(session: Session, *, novel_id: str = "bootstrap-test") -> Novel:
    novel = Novel(
        id=novel_id,
        workspace_id="local",
        title="未命名小说",
        genre="悬疑",
        core_idea="一封寄给未来的信，正在改写收信人的死亡日期。",
        target_words=90000,
        planned_chapters=30,
        writing_profile={
            "bootstrap_status": "running",
            "bootstrap_stage": "blueprint",
            "bootstrap_progress": 8,
        },
    )
    session.add(novel)
    session.commit()
    return novel


def test_blueprint_commit_fills_profile_and_generates_title(session: Session) -> None:
    novel = _novel(session)
    service = BlueprintService(session)
    preview = service.preview(novel)
    result = service.commit(novel, preview_id=preview["previewId"])

    profile = normalize_writing_profile(novel.writing_profile)
    assert result["blueprint"]["book_title"]
    assert novel.title != "未命名小说"
    assert profile_readiness(profile)["ready"] is True
    assert profile["strict_workflow"] is True
    assert profile["auto_generated"] is True
    assert profile["bootstrap_status"] == "running"
    assert len(profile["hard_constraints"]) >= 2


def test_bootstrap_builds_first_writable_batch(session: Session) -> None:
    novel = _novel(session)
    factory = sessionmaker(
        bind=session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )

    service = NovelBootstrapService(session, session_factory=factory)
    result = service.run(novel.id)

    assert result["status"] == "complete", result.get("error")
    assert result["progress"] == 100
    assert result["counts"]["volumes"] == 1
    assert result["counts"]["arcs"] == 3
    assert result["counts"]["chapters"] == 8
    assert result["counts"]["characters"] >= 4
    assert result["counts"]["locations"] >= 3
    assert result["counts"]["factions"] >= 2
    assert result["counts"]["rules"] >= 2
    assert result["firstChapterId"]
    assert result["blueprint"]["bookTitle"] != "未命名小说"

    repeated = service.run(novel.id)
    assert repeated["counts"] == result["counts"]


def test_bible_generation_uses_independent_worker_sessions(
    session: Session, monkeypatch
) -> None:
    novel = _novel(session)
    blueprint_result = BlueprintService(session).commit(
        novel,
        blueprint=BlueprintService(session).preview(novel)["blueprint"],
    )
    worker_sessions: list[object] = []

    class FakeSession:
        def __enter__(self):
            worker_sessions.append(self)
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(
        BibleBootstrapService,
        "_model_config",
        staticmethod(
            lambda _session, _novel_id: SimpleNamespace(
                name="Test Cloud",
                status="connected",
            )
        ),
    )
    result = BibleBootstrapService(
        session,
        session_factory=FakeSession,
    ).build(novel, blueprint=blueprint_result["blueprint"])

    assert len(worker_sessions) == 2
    assert worker_sessions[0] is not worker_sessions[1]
    assert result["draftSources"] == {
        "characters": "model",
        "world": "model",
    }


def test_bible_generation_is_idempotent_and_preserves_locked_fields(
    session: Session,
) -> None:
    novel = _novel(session)
    blueprint_result = BlueprintService(session).commit(
        novel,
        blueprint=BlueprintService(session).preview(novel)["blueprint"],
    )
    blueprint = blueprint_result["blueprint"]
    protagonist_name = blueprint["protagonist"]["name"]
    protected = StoryEntity(
        id="author-protagonist",
        workspace_id=novel.workspace_id,
        novel_id=novel.id,
        entity_type="character",
        name=protagonist_name,
        summary="作者确认的人物摘要",
        data={"role": "作者定义主角", "goal": "作者确认的目标", "status": "已登场"},
        locked_fields=["summary", "data.role", "goal"],
    )
    session.add(protected)
    session.commit()
    factory = sessionmaker(
        bind=session.get_bind(),
        autoflush=False,
        expire_on_commit=False,
    )
    service = BibleBootstrapService(session, session_factory=factory)

    first = service.build(novel, blueprint=blueprint)
    second = service.build(novel, blueprint=blueprint)
    session.refresh(protected)

    assert second["counts"] == first["counts"]
    assert second["counts"]["characters"] >= 4
    assert second["counts"]["locations"] >= 3
    assert second["counts"]["factions"] >= 2
    assert second["counts"]["rules"] >= 2
    assert protected.summary == "作者确认的人物摘要"
    assert protected.data["role"] == "作者定义主角"
    assert protected.data["goal"] == "作者确认的目标"
    assert protected.data["source"] == "auto_bootstrap"
    assert len(
        session.scalars(
            select(StoryEntity).where(StoryEntity.novel_id == novel.id)
        ).all()
    ) == sum(
        second["counts"][key]
        for key in ("characters", "locations", "factions")
    ) + 1
    assert len(
        session.scalars(
            select(NovelRule).where(NovelRule.novel_id == novel.id)
        ).all()
    ) == second["counts"]["rules"]


def test_volume_enrichment_uses_one_session_per_worker(session: Session, monkeypatch) -> None:
    novel = _novel(session)
    worker_sessions: list[object] = []

    class FakeSession:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, model, entity_id):
            assert model is Novel
            assert entity_id == novel.id
            return novel

    def fake_enrich(self, _novel, *, preview_id: str, index: int):
        assert preview_id == "preview"
        worker_sessions.append(self.session)
        return {"node": {"kind": "volume", "title": f"第 {index + 1} 卷", "details": {}}}

    monkeypatch.setattr(
        "app.services_bootstrap.OutlineService.enrich_master_volume",
        fake_enrich,
    )
    service = NovelBootstrapService(
        session,
        session_factory=FakeSession,
        max_workers=3,
    )
    nodes = service._enrich_volumes(novel.id, preview_id="preview", count=3)

    assert len(nodes) == 3
    assert len({id(item) for item in worker_sessions}) == 3


def test_contract_completion_preserves_simple_author_fields(session: Session) -> None:
    novel = _novel(session)
    node = OutlineNode(
        id="simple-chapter-node",
        workspace_id="local",
        novel_id=novel.id,
        parent_id=None,
        kind="chapter",
        title="第 2 章 · 旧信",
        position=1,
        locked=True,
        details={"goal": "查清旧信的寄件人", "must_events": ["主角找到被涂掉的邮戳"]},
    )
    chapter = Chapter(
        id="simple-chapter",
        workspace_id="local",
        novel_id=novel.id,
        outline_node_id=node.id,
        chapter_index=2,
        title="旧信",
        brief=dict(node.details),
    )
    session.add_all([node, chapter])
    session.commit()

    from app.services_outline import OutlineService

    completed = OutlineService(session).complete_chapter_contract(chapter)

    assert completed["contract"]["ready"] is True
    assert chapter.brief["goal"] == "查清旧信的寄件人"
    assert chapter.brief["must_events"] == ["主角找到被涂掉的邮戳"]
    assert chapter.brief["time_anchor"]
    assert chapter.brief["gap_from_previous"]
    assert len(chapter.brief["cpns"]) == 2
    assert node.details == chapter.brief


def test_generation_queue_auto_completes_a_simple_outline(
    session: Session, monkeypatch
) -> None:
    novel = _novel(session)
    node = OutlineNode(
        id="queue-simple-node",
        workspace_id="local",
        novel_id=novel.id,
        parent_id=None,
        kind="chapter",
        title="第 1 章 · 来信",
        position=1,
        locked=True,
        details={"goal": "找到来信者", "must_events": ["主角辨认出信纸来源"]},
    )
    chapter = Chapter(
        id="queue-simple-chapter",
        workspace_id="local",
        novel_id=novel.id,
        outline_node_id=node.id,
        chapter_index=1,
        title="来信",
        brief=dict(node.details),
    )
    session.add_all([node, chapter])
    session.commit()
    monkeypatch.setattr("app.routes.run_generation", lambda *_args: None)

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.post(
                f"/api/chapters/{chapter.id}/generate",
                json={"base_version_id": None, "goal": "找到来信者"},
            )
        assert response.status_code == 202, response.json()
        session.refresh(chapter)
        assert chapter.brief["goal"] == "找到来信者"
        assert chapter.brief["time_anchor"]
        assert chapter.brief["cbn"]
        assert len(chapter.brief["cpns"]) == 2
        assert chapter.brief["cen"]
    finally:
        app.dependency_overrides.clear()


def test_auto_bootstrap_creation_is_queued(session: Session, monkeypatch) -> None:
    scheduled: list[str] = []
    monkeypatch.setattr(
        "app.routes.run_novel_bootstrap",
        lambda novel_id: scheduled.append(novel_id),
    )

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/novels",
                json={
                    "title": "未命名小说",
                    "genre": "悬疑",
                    "core_idea": "一个失忆的人收到未来自己寄来的证词。",
                    "auto_bootstrap": True,
                },
            )
            novel_id = response.json()["id"]
            status = client.get(f"/api/novels/{novel_id}/bootstrap")
            novel = session.get(Novel, novel_id)
            assert novel is not None
            failed_profile = normalize_writing_profile(novel.writing_profile)
            failed_profile.update(
                {
                    "bootstrap_status": "failed",
                    "bootstrap_stage": "volumes",
                    "bootstrap_error": "temporary failure",
                }
            )
            novel.writing_profile = failed_profile
            session.commit()
            retried = client.post(f"/api/novels/{novel_id}/bootstrap/retry")
        assert response.status_code == 201
        body = response.json()
        assert body["writingProfile"]["bootstrap_status"] == "pending"
        assert body["writingProfile"]["strict_workflow"] is False
        assert status.status_code == 200
        assert status.json()["status"] == "pending"
        assert retried.status_code == 202
        assert retried.json()["status"] == "pending"
        assert scheduled == [body["id"], body["id"]]
    finally:
        app.dependency_overrides.clear()


def test_auto_bootstrap_requires_a_connected_cloud_model(session: Session) -> None:
    for model in session.scalars(select(ModelConfig)).all():
        session.delete(model)
    session.commit()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/novels",
                json={
                    "title": "未命名小说",
                    "genre": "悬疑",
                    "core_idea": "一封不存在寄件人的信。",
                    "auto_bootstrap": True,
                },
            )
        assert response.status_code == 409
        assert "云端模型" in str(response.json()["detail"])
    finally:
        app.dependency_overrides.clear()


def test_chapter_generation_requires_a_connected_cloud_model(session: Session) -> None:
    for model in session.scalars(select(ModelConfig)).all():
        session.delete(model)
    session.commit()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/chapters/c12/generate",
                json={"base_version_id": None, "goal": "继续调查信标"},
            )
        assert response.status_code == 409
        assert "云端写作模型" in str(response.json()["detail"])
    finally:
        app.dependency_overrides.clear()
