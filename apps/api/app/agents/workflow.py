from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..models import Chapter, ModelConfig
from .memory_agent import AgentScopeMemoryAgent, heuristic_memory_delta
from .models import model_config_for_role
from .plot import AgentScopePlotAgent, heuristic_plot_plan
from .skills_runtime import SkillRuntime


def plan_scene_beats(
    session: Session,
    *,
    chapter: Chapter,
    brief: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    config = model_config_for_role(session, chapter.novel_id, "大纲")
    if config is None:
        config = model_config_for_role(session, chapter.novel_id, "写作")
    if config is not None:
        try:
            return AgentScopePlotAgent(config).plan(
                title=chapter.title, brief=brief, context=context
            )
        except Exception:
            pass
    return heuristic_plot_plan(title=chapter.title, brief=brief)


def run_continuity_skill(
    session: Session,
    *,
    chapter: Chapter,
    content: str,
    protected_texts: list[str],
    must_events: list[str],
    forbidden_events: list[str] | None = None,
) -> dict[str, Any]:
    runtime = SkillRuntime(
        session, novel_id=chapter.novel_id, chapter_id=chapter.id
    )
    return runtime.invoke(
        skill_name="continuity-check",
        agent_name="Continuity",
        payload={
            "content": content,
            "protected_texts": protected_texts,
            "must_events": must_events,
            "forbidden_events": forbidden_events or [],
            "chapter_index": chapter.chapter_index,
        },
    )


def extract_memory_delta(
    session: Session,
    *,
    chapter: Chapter,
    content: str,
    existing_entities: list[dict[str, Any]],
    existing_threads: list[dict[str, Any]],
) -> dict[str, Any]:
    config = model_config_for_role(session, chapter.novel_id, "提取")
    if config is None:
        config = model_config_for_role(session, chapter.novel_id, "审计")
    if config is not None:
        try:
            return AgentScopeMemoryAgent(config).extract(
                title=chapter.title,
                content=content,
                brief=chapter.brief or {},
                existing_entities=existing_entities,
                existing_threads=existing_threads,
            )
        except Exception:
            pass
    return heuristic_memory_delta(
        title=chapter.title,
        content=content,
        brief=chapter.brief or {},
        chapter_index=chapter.chapter_index,
    )


def writer_model_config(session: Session, novel_id: str) -> ModelConfig | None:
    return model_config_for_role(session, novel_id, "写作")
