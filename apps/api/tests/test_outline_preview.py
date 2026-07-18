"""Outline preview/commit + coherence (mainstream flow B)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.skills_runtime import SkillRuntime, ensure_default_skills
from app.memory.outline_preview_store import get_preview
from app.models import Chapter, Novel, OutlineNode, PlotThread, Skill, StoryBeat, StoryEntity, StoryEvent
from app.services_blueprint import BlueprintService
from app.services_outline import OutlineService


def _blank_novel(session: Session) -> Novel:
    novel = Novel(
        id="outline-blueprint",
        workspace_id="local",
        title="蓝图测试",
        genre="科幻",
        core_idea="一名维修师追查失控的轨道城。",
        planned_chapters=80,
    )
    session.add(novel)
    session.flush()
    return novel


def test_outline_coherence_skill(session: Session) -> None:
    ensure_default_skills(session)
    skill = session.scalar(select(Skill).where(Skill.name == "outline-coherence"))
    assert skill is not None
    runtime = SkillRuntime(session, novel_id="starfarer")
    result = runtime.invoke(
        skill_name="outline-coherence",
        agent_name="Outline",
        payload={
            "nodes": [
                {
                    "title": "第 1 章 · A",
                    "details": {
                        "goal": "寻找失落的信标坐标",
                        "must_events": ["发现信标"],
                        "hook": "第二枚信号",
                    },
                },
                {
                    "title": "第 2 章 · B",
                    "details": {
                        "goal": "寻找失落的信标坐标",  # similar
                        "must_events": [],
                        "hook": "",
                    },
                },
            ],
            "existing_titles": ["第 1 章 · A"],
            "prior_chapter_briefs": [],
        },
    )
    assert result["ok"] is True
    assert result["issue_count"] >= 1


def test_preview_does_not_write_nodes(session: Session) -> None:
    novel = session.get(Novel, "starfarer")
    assert novel is not None
    before = len(
        session.scalars(select(OutlineNode).where(OutlineNode.novel_id == novel.id)).all()
    )
    preview = OutlineService(session).preview_children(
        novel,
        parent_id="arc1",
        child_kind="chapter",
        count=2,
        create_chapters=True,
        mode="batch_chapters",
    )
    assert preview["previewId"]
    assert len(preview["nodes"]) == 2
    assert get_preview(session, preview["previewId"], novel_id=novel.id) is not None
    after = len(
        session.scalars(select(OutlineNode).where(OutlineNode.novel_id == novel.id)).all()
    )
    assert after == before


def test_commit_writes_selected_only(session: Session) -> None:
    novel = session.get(Novel, "starfarer")
    assert novel is not None
    preview = OutlineService(session).preview_children(
        novel,
        parent_id="arc1",
        child_kind="chapter",
        count=3,
        mode="batch_chapters",
    )
    nodes = list(preview["nodes"])
    nodes[1]["selected"] = False
    sibling_before = len(
        session.scalars(select(OutlineNode).where(OutlineNode.parent_id == "arc1")).all()
    )
    chapter_before = len(
        session.scalars(select(Chapter).where(Chapter.novel_id == novel.id)).all()
    )
    result = OutlineService(session).commit_preview(
        novel, preview_id=preview["previewId"], nodes=nodes
    )
    assert len(result["created"]) == 2
    assert result["chaptersCreated"] == 2
    sibling_after = len(
        session.scalars(select(OutlineNode).where(OutlineNode.parent_id == "arc1")).all()
    )
    assert sibling_after == sibling_before + 2
    chapter_after = len(
        session.scalars(select(Chapter).where(Chapter.novel_id == novel.id)).all()
    )
    assert chapter_after == chapter_before + 2
    assert get_preview(session, preview["previewId"], novel_id=novel.id) is None


def test_preview_survives_a_new_database_session(session: Session) -> None:
    novel = session.get(Novel, "starfarer")
    assert novel is not None
    preview = OutlineService(session).preview_children(
        novel,
        parent_id="arc1",
        child_kind="chapter",
        count=1,
        create_chapters=True,
    )

    with Session(session.get_bind(), expire_on_commit=False) as restarted_session:
        restarted_novel = restarted_session.get(Novel, novel.id)
        assert restarted_novel is not None
        result = OutlineService(restarted_session).commit_preview(
            restarted_novel,
            preview_id=preview["previewId"],
            nodes=preview["nodes"],
        )

    assert len(result["created"]) == 1


def test_master_preview_requires_confirmed_blueprint(session: Session) -> None:
    novel = _blank_novel(session)
    try:
        OutlineService(session).master_preview(novel)
        assert False, "expected blueprint requirement"
    except ValueError as exc:
        assert "故事蓝图" in str(exc)


def test_master_preview_generates_volumes_after_blueprint(session: Session) -> None:
    novel = _blank_novel(session)
    blueprint_service = BlueprintService(session)
    blueprint_preview = blueprint_service.preview(novel)
    blueprint_service.commit(novel, preview_id=blueprint_preview["previewId"])

    before_nodes = len(
        session.scalars(select(OutlineNode).where(OutlineNode.novel_id == novel.id)).all()
    )
    preview = OutlineService(session).master_preview(novel, volume_count=2)
    assert preview.get("master") is True
    assert preview["stage"] == "volumes"
    assert preview["childKind"] == "volume"
    assert len(preview["nodes"]) == 2
    assert all((node.get("details") or {}).get("planned_chapters", 0) > 0 for node in preview["nodes"])
    assert all(isinstance((node.get("details") or {}).get("characters"), list) for node in preview["nodes"])
    assert all(isinstance((node.get("details") or {}).get("locations"), list) for node in preview["nodes"])
    assert all(isinstance((node.get("details") or {}).get("plot_arcs"), list) for node in preview["nodes"])
    after_nodes = len(
        session.scalars(select(OutlineNode).where(OutlineNode.novel_id == novel.id)).all()
    )
    assert after_nodes == before_nodes


def test_master_preview_returns_fast_skeleton_without_model(session: Session, monkeypatch) -> None:
    novel = _blank_novel(session)
    novel.planned_chapters = 400
    blueprint_service = BlueprintService(session)
    blueprint_preview = blueprint_service.preview(novel)
    blueprint_service.commit(novel, preview_id=blueprint_preview["previewId"])

    monkeypatch.setattr(
        OutlineService,
        "_draft_nodes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("model called")),
    )
    preview = OutlineService(session).master_preview(novel, volume_count=7)
    assert len(preview["nodes"]) == 7
    assert preview["draftSource"] == "blueprint"
    assert preview["enrichmentPending"] is True
    assert preview["modelFallback"] is False


def test_master_volume_enrichment_preserves_skeleton_budget(session: Session, monkeypatch) -> None:
    novel = _blank_novel(session)
    novel.planned_chapters = 120
    BlueprintService(session).commit(
        novel,
        blueprint={
            "book_title": "轨道余烬",
            "genre": "科幻",
            "logline": "重建轨道城",
            "arcs_outline": ["第一卷：求生", "第二卷：反击"],
        },
    )
    preview = OutlineService(session).master_preview(novel, volume_count=2)
    original_budget = preview["nodes"][0]["details"]["planned_chapters"]
    monkeypatch.setattr(
        OutlineService,
        "_draft_nodes",
        lambda *_args, **_kwargs: (
            [
                {
                    "kind": "volume",
                    "title": "模型擅自改名",
                    "details": {
                        "planned_chapters": 999,
                        "arc_summary": "补全后的梗概",
                        "characters": ["维修师"],
                    },
                }
            ],
            "model",
            False,
        ),
    )

    enriched = OutlineService(session).enrich_master_volume(
        novel, preview_id=preview["previewId"], index=0
    )
    assert enriched["node"]["title"] == preview["nodes"][0]["title"]
    assert enriched["node"]["details"]["planned_chapters"] == original_budget
    assert enriched["node"]["details"]["arc_summary"] == "补全后的梗概"


def test_master_preview_uses_ai_blueprint_stage_count(session: Session) -> None:
    novel = _blank_novel(session)
    novel.planned_chapters = 240
    BlueprintService(session).commit(
        novel,
            blueprint={
                "book_title": "轨道余烬",
                "genre": "科幻",
                "logline": "维修师重建轨道城",
            "arcs_outline": ["失控", "求生", "反击", "重建"],
        },
    )

    preview = OutlineService(session).master_preview(novel, run_coherence=False)
    assert preview["volumeCountSource"] == "blueprint_ai"
    assert preview["blueprintStageCount"] == 4
    assert len(preview["nodes"]) == 4
    assert sum(node["details"]["planned_chapters"] for node in preview["nodes"]) == 240


def test_batch_chapters_requires_arc_parent(session: Session) -> None:
    novel = session.get(Novel, "starfarer")
    assert novel is not None
    try:
        OutlineService(session).preview_children(
            novel,
            parent_id="vol1",
            child_kind="chapter",
            count=2,
            mode="batch_chapters",
        )
        assert False, "expected arc parent requirement"
    except ValueError as exc:
        assert "剧情弧" in str(exc)


def test_delete_arc_removes_descendant_chapters(session: Session) -> None:
    novel = session.get(Novel, "starfarer")
    assert novel is not None
    chapter = Chapter(
        id="delete-arc-chapter",
        workspace_id="local",
        novel_id=novel.id,
        outline_node_id="oc1",
        chapter_index=999,
        title="待删除章节",
    )
    session.add(chapter)
    session.flush()
    result = OutlineService(session).delete_node("arc1")
    assert result["deletedNodes"] >= 1
    assert session.get(OutlineNode, "arc1") is None
    assert session.get(OutlineNode, "oc1") is None
    assert len(
        session.scalars(select(Chapter).where(Chapter.outline_node_id == "oc1")).all()
    ) == 0


def test_outline_entities_sync_on_commit_and_delete(session: Session) -> None:
    novel = session.get(Novel, "starfarer")
    assert novel is not None
    preview = OutlineService(session).preview_children(
        novel,
        parent_id="arc1",
        child_kind="chapter",
        count=1,
        mode="batch_chapters",
    )
    node = preview["nodes"][0]
    node["details"]["characters"] = ["大纲同步角色"]
    node["details"]["locations"] = ["大纲同步地点"]
    node["details"]["must_events"] = ["在废弃港口截获失控信号"]
    node["details"]["highlight"] = "信号投影出失踪者的坐标"
    node["details"]["twist"] = "坐标指向敌方控制区"
    node["details"]["foreshadow_plant"] = ["失踪者坐标的来历"]
    OutlineService(session).commit_preview(
        novel, preview_id=preview["previewId"], nodes=[node]
    )

    character = session.scalar(
        select(StoryEntity).where(
            StoryEntity.novel_id == novel.id,
            StoryEntity.entity_type == "character",
            StoryEntity.name == "大纲同步角色",
        )
    )
    location = session.scalar(
        select(StoryEntity).where(
            StoryEntity.novel_id == novel.id,
            StoryEntity.entity_type == "location",
            StoryEntity.name == "大纲同步地点",
        )
    )
    assert character is not None
    assert location is not None
    created_node = session.scalar(
        select(OutlineNode).where(
            OutlineNode.parent_id == "arc1", OutlineNode.title == node["title"]
        )
    )
    assert created_node is not None
    assert session.scalar(
        select(StoryEvent).where(StoryEvent.source_outline_node_id == created_node.id)
    ) is not None
    assert session.scalar(
        select(StoryBeat).where(StoryBeat.source_outline_node_id == created_node.id)
    ) is not None
    assert session.scalar(
        select(PlotThread).where(PlotThread.source_outline_node_id == created_node.id)
    ) is not None

    OutlineService(session).delete_node("arc1")
    assert session.get(StoryEntity, character.id) is None
    assert session.get(StoryEntity, location.id) is None
    assert session.scalar(
        select(StoryEvent).where(StoryEvent.source_outline_node_id == created_node.id)
    ) is None
    assert session.scalar(
        select(StoryBeat).where(StoryBeat.source_outline_node_id == created_node.id)
    ) is None
    assert session.scalar(
        select(PlotThread).where(PlotThread.source_outline_node_id == created_node.id)
    ) is None


def test_batch_chapters_include_per_node_pacing(session: Session) -> None:
    novel = session.get(Novel, "starfarer")
    assert novel is not None
    preview = OutlineService(session).preview_children(
        novel,
        parent_id="arc1",
        child_kind="chapter",
        count=3,
        mode="batch_chapters",
    )
    pacing = [node.get("details", {}).get("pacing", {}) for node in preview["nodes"]]
    assert [item.get("index") for item in pacing] == [1, 2, 3]
    assert all(item.get("phase") for item in pacing)


def test_appended_volume_uses_remaining_budget_for_legacy_outline(session: Session) -> None:
    novel = session.get(Novel, "starfarer")
    assert novel is not None
    blueprint_service = BlueprintService(session)
    blueprint_preview = blueprint_service.preview(novel)
    blueprint_service.commit(novel, preview_id=blueprint_preview["previewId"])

    preview = OutlineService(session).preview_children(
        novel,
        parent_id=None,
        child_kind="volume",
        count=1,
        mode="children",
    )
    # The seeded first volume has seven chapter nodes and no legacy budget.
    assert preview["nodes"][0]["details"]["planned_chapters"] == 73


def test_regenerate_node_preview_and_commit(session: Session) -> None:
    novel = session.get(Novel, "starfarer")
    assert novel is not None
    node = session.scalars(
        select(OutlineNode).where(
            OutlineNode.novel_id == novel.id,
            OutlineNode.kind == "chapter",
            OutlineNode.locked.is_(False),
        )
    ).first()
    assert node is not None
    old_details = dict(node.details or {})
    preview = OutlineService(session).preview_regenerate_node(novel, node_id=node.id)
    assert preview["mode"] == "regenerate_node"
    assert preview["targetNodeId"] == node.id
    assert len(preview["nodes"]) == 1
    assert preview["nodes"][0].get("details")

    # Mutate preview title slightly then commit replace
    nodes = list(preview["nodes"])
    nodes[0]["details"] = {
        **(nodes[0].get("details") or {}),
        "goal": "重新生成后的测试目标",
        "highlight": "新亮点",
        "twist": "新转折",
        "hook": "新钩子",
        "must_events": ["新事件"],
    }
    result = OutlineService(session).commit_preview(
        novel, preview_id=preview["previewId"], nodes=nodes
    )
    assert result.get("replacedNodeId") == node.id
    session.refresh(node)
    assert (node.details or {}).get("goal") == "重新生成后的测试目标"
    assert (node.details or {}).get("highlight") == "新亮点"
    # Ensure we actually changed something vs original when original lacked goal
    assert node.details != old_details or old_details.get("goal") == "重新生成后的测试目标"


def test_regenerate_locked_node_rejected(session: Session) -> None:
    novel = session.get(Novel, "starfarer")
    assert novel is not None
    locked = session.scalars(
        select(OutlineNode).where(
            OutlineNode.novel_id == novel.id,
            OutlineNode.locked.is_(True),
        )
    ).first()
    if locked is None:
        locked = session.scalars(
            select(OutlineNode).where(
                OutlineNode.novel_id == novel.id,
                OutlineNode.kind == "chapter",
            )
        ).first()
        assert locked is not None
        locked.locked = True
        session.commit()
    try:
        OutlineService(session).preview_regenerate_node(novel, node_id=locked.id)
        assert False, "expected locked rejection"
    except ValueError as exc:
        assert "锁定" in str(exc)
