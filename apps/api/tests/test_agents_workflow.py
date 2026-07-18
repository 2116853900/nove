from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.plot import heuristic_plot_plan, normalize_plot_plan
from app.agents.memory_agent import heuristic_memory_delta, normalize_memory_delta
from app.agents.skills_runtime import SkillRuntime, ensure_default_skills
from app.models import Chapter, ChapterVersion, Skill, SkillRun, StoryEvent
from app.services import GenerationService, MemoryService


def test_heuristic_plot_plan_covers_must_events() -> None:
    plan = heuristic_plot_plan(
        title="测试章",
        brief={
            "goal": "找到信标",
            "must_events": ["锁定坐标", "燃料不足被提出"],
            "forbidden_events": ["提前揭秘"],
            "hook": "第二枚信标",
        },
    )
    assert len(plan["beats"]) >= 3
    assert "锁定坐标" in plan["must_cover"]
    assert "提前揭秘" in plan["avoid"]


def test_normalize_plot_plan_fallback_on_empty() -> None:
    plan = normalize_plot_plan({}, brief={"goal": "推进", "must_events": ["A"]})
    assert plan["beats"]
    assert plan["must_cover"] == ["A"]


def test_normalize_memory_delta() -> None:
    data = normalize_memory_delta(
        {
            "events": [{"action": "发现信标", "subjects": ["林远"]}],
            "entity_updates": [{"name": "林远", "summary": "更坚定", "facts": {"mood": "坚定"}}],
            "plot_threads": [{"name": "信标来源", "status": "DEVELOPING", "latest": "新线索"}],
            "resolved_threads": [],
        }
    )
    assert data["events"][0]["action"] == "发现信标"
    assert data["entity_updates"][0]["name"] == "林远"
    assert data["plot_threads"][0]["status"] == "DEVELOPING"


def test_skill_runtime_whitelist_and_continuity(session: Session) -> None:
    ensure_default_skills(session)
    runtime = SkillRuntime(session, novel_id="starfarer", chapter_id="c1")

    denied = runtime.invoke(
        skill_name="continuity-check",
        agent_name="UnknownAgent",
        payload={"content": "正文"},
    )
    assert denied["ok"] is False

    ok = runtime.invoke(
        skill_name="continuity-check",
        agent_name="Continuity",
        payload={
            "content": "他早就知道答案。",
            "protected_texts": ["锁定句"],
            "must_events": ["锁定坐标"],
        },
    )
    assert ok["ok"] is True
    assert ok["pass"] is False
    assert ok["issue_count"] >= 2
    runs = session.scalars(select(SkillRun)).all()
    assert len(runs) >= 2


def test_entity_lookup_skill(session: Session) -> None:
    ensure_default_skills(session)
    runtime = SkillRuntime(session, novel_id="starfarer", chapter_id="c1")
    result = runtime.invoke(
        skill_name="entity-lookup",
        agent_name="Writer",
        payload={"name": "林远"},
    )
    assert result["ok"] is True
    assert any(item["name"] == "林远" for item in result["matches"])


def test_generation_includes_plot_and_continuity(session: Session) -> None:
    chapter = session.get(Chapter, "c1")
    assert chapter is not None
    job = GenerationService(session).create_job(
        chapter, chapter.current_version_id, "GENERATE_CHAPTER"
    )
    GenerationService(session).run_job(job.id, auto_audit=True)
    session.refresh(job)
    assert job.state == "COMPLETED"
    assert job.result.get("plotPlan")
    assert "beats" in job.result["plotPlan"]
    assert "continuity" in job.result
    manifest = job.result["contextManifest"]
    assert manifest["outlineNodes"] >= 1
    assert "ragChunks" in manifest
    assert "recentChapters" in manifest
    assert "characterStates" in manifest
    assert manifest["retrievalQuery"]
    stages = [e.get("stage") for e in job.events if e.get("type") == "progress"]
    assert "正在设计场景节拍" in stages
    assert "正在检查连续性" in stages


def test_confirm_commits_memory_events(session: Session) -> None:
    chapter = session.get(Chapter, "c2")
    assert chapter is not None and chapter.current_version_id
    version = session.get(ChapterVersion, chapter.current_version_id)
    assert version is not None
    # Ensure content contains a must event phrase for heuristic extraction.
    chapter.brief = {
        **(chapter.brief or {}),
        "must_events": ["推动当前冲突"],
    }
    version.content = (version.content or "") + "\n\n推动当前冲突并作出新的选择。"
    session.commit()

    before = session.scalar(
        select(StoryEvent).where(StoryEvent.chapter_id == chapter.id)
    )
    result = MemoryService(session).commit_confirmed_memory(chapter, version)
    assert result["chunks"] >= 0
    assert result["committed"]["events"] >= 1
    after = session.scalars(
        select(StoryEvent).where(StoryEvent.chapter_id == chapter.id)
    ).all()
    assert len(after) >= (1 if before is None else 1)
