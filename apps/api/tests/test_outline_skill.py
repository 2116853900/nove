"""Outline generation via SkillRuntime (AI writing flow — outline stage)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.skills_runtime import SkillRuntime, ensure_default_skills
from app.models import Novel, OutlineNode, Skill, SkillRun
from app.services_outline import OutlineService


def test_outline_generate_skill_is_registered(session: Session) -> None:
    ensure_default_skills(session)
    skill = session.scalar(select(Skill).where(Skill.name == "outline-generate"))
    assert skill is not None
    assert skill.enabled is True
    assert "Outline" in (skill.allowed_agents or []) or "Plot" in (skill.allowed_agents or [])
    required = (skill.input_schema or {}).get("required") or []
    assert "child_kind" in required
    assert "count" in required


def test_outline_generate_skill_denies_unauthorized_agent(session: Session) -> None:
    ensure_default_skills(session)
    runtime = SkillRuntime(session, novel_id="starfarer")
    denied = runtime.invoke(
        skill_name="outline-generate",
        agent_name="UnknownAgent",
        payload={
            "child_kind": "chapter",
            "count": 2,
            "novel": {"title": "星河", "coreIdea": "信标"},
            "existing_titles": [],
        },
    )
    assert denied["ok"] is False
    assert "not allowed" in (denied.get("error") or "").lower() or denied.get("error")


def test_outline_generate_skill_returns_nodes(session: Session) -> None:
    ensure_default_skills(session)
    runtime = SkillRuntime(session, novel_id="starfarer")
    result = runtime.invoke(
        skill_name="outline-generate",
        agent_name="Outline",
        payload={
            "child_kind": "chapter",
            "count": 2,
            "novel": {"title": "星河旅人", "coreIdea": "信标坠落"},
            "parent": {"title": "第一卷 · 启航", "kind": "arc"},
            "existing_titles": ["第 1 章 · 坠落"],
            "start_chapter_index": 4,
        },
    )
    assert result["ok"] is True
    assert result.get("source") in {"model", "heuristic"}
    nodes = result.get("nodes") or []
    assert len(nodes) == 2
    assert all(n.get("kind") == "chapter" for n in nodes)
    assert all(str(n.get("title") or "").strip() for n in nodes)
    # SkillRun logged
    runs = session.scalars(
        select(SkillRun).where(SkillRun.skill_name == "outline-generate")
    ).all()
    assert any(r.status == "ok" for r in runs)


def test_outline_generate_skill_auto_plans_arc_count(session: Session) -> None:
    ensure_default_skills(session)
    result = SkillRuntime(session, novel_id="starfarer").invoke(
        skill_name="outline-generate",
        agent_name="Outline",
        payload={
            "child_kind": "arc",
            "count": 0,
            "novel": {"title": "星河旅人", "coreIdea": "信标坠落", "plannedChapters": 48},
            "parent": {
                "title": "第一卷 · 启航",
                "kind": "volume",
                "details": {"planned_chapters": 24},
            },
            "existing_titles": [],
        },
    )
    nodes = result.get("nodes") or []
    assert result["ok"] is True
    assert len(nodes) >= 1
    assert all(node.get("kind") == "arc" for node in nodes)
    assert all(node.get("details", {}).get("planned_chapters", 0) > 0 for node in nodes)


def test_outline_generate_model_receives_hierarchical_context(session: Session, monkeypatch) -> None:
    """Regression: the configured-model branch must not silently NameError."""
    ensure_default_skills(session)
    captured: dict[str, object] = {}

    class FakeOutlineAgent:
        def __init__(self, _config: object):
            pass

        def generate_children(self, **kwargs: object) -> list[dict[str, object]]:
            captured.update(kwargs)
            return [
                {
                    "kind": "chapter",
                    "title": "第 4 章 · 信号回响",
                    "details": {
                        "goal": "追查失真的信号来源",
                        "conflict": "燃料不足",
                        "must_events": ["截获异常频段"],
                        "highlight": "发现父亲留下的加密坐标",
                        "twist": "坐标指向禁飞区",
                        "hook": "禁飞区传来回应",
                    },
                }
            ]

    monkeypatch.setattr(
        "app.agents.models.model_config_for_role",
        lambda *_args, **_kwargs: SimpleNamespace(status="connected"),
    )
    monkeypatch.setattr("app.agents.outline.AgentScopeOutlineAgent", FakeOutlineAgent)

    result = SkillRuntime(session, novel_id="starfarer").invoke(
        skill_name="outline-generate",
        agent_name="Outline",
        payload={
            "child_kind": "chapter",
            "count": 1,
            "novel": {"title": "星河旅人", "coreIdea": "信标坠落"},
            "parent": {"kind": "arc", "title": "剧情弧 · 改变航向"},
            "existing_titles": [],
            "blueprint": {"logline": "宇航员追查失控信标"},
            "volume_plan": {"stage_goal": "确认信标来源"},
            "arc_plan": {"goal": "改变航向", "planned_chapters": 12},
            "pacing": {"nodes": [{"index": 1, "phase": "setup"}]},
            "unresolved_foreshadow": ["父亲失踪之谜"],
        },
    )

    assert result["ok"] is True
    assert result["source"] == "model"
    assert captured["blueprint"] == {"logline": "宇航员追查失控信标"}
    assert captured["volume_plan"] == {"stage_goal": "确认信标来源"}
    assert captured["arc_plan"] == {"goal": "改变航向", "planned_chapters": 12}
    assert captured["pacing"] == {"nodes": [{"index": 1, "phase": "setup"}]}


def test_outline_generate_preserves_zero_count_for_ai_volume_planning(
    session: Session, monkeypatch
) -> None:
    ensure_default_skills(session)
    captured: dict[str, object] = {}

    class FakeOutlineAgent:
        def __init__(self, _config: object):
            pass

        def generate_children(self, **kwargs: object) -> list[dict[str, object]]:
            captured.update(kwargs)
            return [
                {"kind": "volume", "title": "第一卷", "details": {"planned_chapters": 60}},
                {"kind": "volume", "title": "第二卷", "details": {"planned_chapters": 40}},
            ]

    monkeypatch.setattr(
        "app.agents.models.model_config_for_role",
        lambda *_args, **_kwargs: SimpleNamespace(status="connected"),
    )
    monkeypatch.setattr("app.agents.outline.AgentScopeOutlineAgent", FakeOutlineAgent)

    result = SkillRuntime(session, novel_id="starfarer").invoke(
        skill_name="outline-generate",
        agent_name="Outline",
        payload={
            "child_kind": "volume",
            "count": 0,
            "mode": "master_outline",
            "novel": {"title": "星河旅人", "plannedChapters": 100},
            "existing_titles": [],
        },
    )

    assert captured["count"] == 0
    assert result["count"] == 2


def test_batch_chapters_calls_model_once_per_chapter(session: Session, monkeypatch) -> None:
    """Long chapter batches are serialized to keep every model response small."""
    from agentscope import agent as agent_module
    from app.agents import outline as outline_module

    calls: list[dict[str, object]] = []

    class FakeOutlineAgent:
        def __init__(self, **_kwargs: object):
            pass

        async def reply(self, message: object) -> SimpleNamespace:
            content = getattr(message, "content")
            if isinstance(content, list):
                content = getattr(content[0], "text", "")
            payload = json.loads(str(content).split("\n", 1)[1])
            calls.append(payload)
            index = int(payload["startChapterIndex"])
            return SimpleNamespace(
                content=json.dumps(
                    {
                        "nodes": [
                            {
                                "kind": "chapter",
                                "title": f"第 {index} 章 · 逐章生成",
                                "details": {"goal": f"推进第 {index} 章", "hook": "留下悬念"},
                            }
                        ]
                    },
                    ensure_ascii=False,
                )
            )

    monkeypatch.setattr(agent_module, "Agent", FakeOutlineAgent)
    monkeypatch.setattr(
        outline_module,
        "build_chat_model",
        lambda *_args, **_kwargs: SimpleNamespace(parameters=SimpleNamespace(temperature=0.0)),
    )

    result = outline_module.AgentScopeOutlineAgent(SimpleNamespace(name="test-model")).generate_children(
        novel={"title": "星河旅人"},
        parent={"kind": "arc", "title": "剧情弧 · 改变航向"},
        child_kind="chapter",
        count=3,
        existing_titles=[],
        start_chapter_index=4,
        mode="batch_chapters",
    )

    assert len(result) == 3
    assert [call["count"] for call in calls] == [1, 1, 1]
    assert [call["startChapterIndex"] for call in calls] == [4, 5, 6]


def test_outline_service_uses_skill_and_logs(session: Session) -> None:
    ensure_default_skills(session)
    novel = session.get(Novel, "starfarer")
    assert novel is not None
    before_runs = len(
        session.scalars(
            select(SkillRun).where(SkillRun.skill_name == "outline-generate")
        ).all()
    )
    sibling_count = len(
        session.scalars(select(OutlineNode).where(OutlineNode.parent_id == "arc1")).all()
    )
    result = OutlineService(session).generate_children(
        novel,
        parent_id="arc1",
        child_kind="chapter",
        count=2,
        create_chapters=True,
    )
    assert len(result["created"]) == 2
    assert result.get("draftSource") in {"model", "heuristic", "skill"}
    after = session.scalars(select(OutlineNode).where(OutlineNode.parent_id == "arc1")).all()
    assert len(after) == sibling_count + 2
    after_runs = session.scalars(
        select(SkillRun).where(SkillRun.skill_name == "outline-generate")
    ).all()
    assert len(after_runs) > before_runs


def test_outline_skill_schema_requires_fields(session: Session) -> None:
    ensure_default_skills(session)
    runtime = SkillRuntime(session, novel_id="starfarer")
    bad = runtime.invoke(
        skill_name="outline-generate",
        agent_name="Outline",
        payload={"novel": {"title": "x"}},  # missing child_kind / count
    )
    assert bad["ok"] is False
    assert "missing" in (bad.get("error") or "").lower()
