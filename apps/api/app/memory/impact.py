from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain import ChapterState
from ..models import Chapter, PlotThread, StoryEntity, StoryEvent


def compute_impact(
    session: Session,
    *,
    chapter: Chapter,
    old_delta: dict[str, Any] | None,
    new_delta: dict[str, Any],
    force: bool = False,
) -> dict[str, Any]:
    """Diff memory deltas and mark later chapters that share entities/threads.

    When ``force`` is True (re-confirm of a previously confirmed chapter),
    every later confirmed chapter is marked OUTDATED even if the heuristic
    delta looks identical.
    """
    old_delta = old_delta or {}
    changed_entities: set[str] = set()
    changed_threads: set[str] = set()
    changed_actions: set[str] = set()

    old_events = {
        str(e.get("action") or "")
        for e in (old_delta.get("events") or [])
        if isinstance(e, dict)
    }
    new_events = {
        str(e.get("action") or "")
        for e in (new_delta.get("events") or [])
        if isinstance(e, dict)
    }
    changed_actions |= old_events.symmetric_difference(new_events)

    for item in new_delta.get("events") or []:
        if isinstance(item, dict):
            for name in item.get("subjects") or []:
                if name:
                    changed_entities.add(str(name))

    old_entities = {
        str(e.get("name") or "")
        for e in (old_delta.get("entity_updates") or [])
        if isinstance(e, dict)
    }
    new_entities = {
        str(e.get("name") or "")
        for e in (new_delta.get("entity_updates") or [])
        if isinstance(e, dict)
    }
    changed_entities |= old_entities.symmetric_difference(new_entities)
    for item in new_delta.get("entity_updates") or []:
        if isinstance(item, dict) and item.get("name"):
            changed_entities.add(str(item["name"]))

    old_threads = {
        str(t.get("name") or "")
        for t in (old_delta.get("plot_threads") or [])
        if isinstance(t, dict)
    }
    new_threads = {
        str(t.get("name") or "")
        for t in (new_delta.get("plot_threads") or [])
        if isinstance(t, dict)
    }
    changed_threads |= old_threads.symmetric_difference(new_threads)
    for name in new_delta.get("resolved_threads") or []:
        changed_threads.add(str(name))

    facts_changed = bool(changed_entities or changed_threads or changed_actions or force)

    later = session.scalars(
        select(Chapter).where(
            Chapter.novel_id == chapter.novel_id,
            Chapter.chapter_index > chapter.chapter_index,
        )
    ).all()

    affected: list[dict[str, Any]] = []
    for item in later:
        reasons: list[str] = []
        blob = " ".join(
            [
                item.title,
                str((item.brief or {}).get("goal") or ""),
                " ".join((item.brief or {}).get("must_events") or []),
                " ".join((item.brief or {}).get("characters") or []),
            ]
        )
        for name in changed_entities:
            if name and name in blob:
                reasons.append(f"实体「{name}」")
        for name in changed_threads:
            if name and name in blob:
                reasons.append(f"剧情线「{name}」")

        later_events = session.scalars(
            select(StoryEvent).where(StoryEvent.chapter_id == item.id)
        ).all()
        for event in later_events:
            for name in changed_entities:
                if name in (event.subjects or []) or name in (event.action or ""):
                    reasons.append(f"事件引用「{name}」")
                    break

        is_confirmed = bool(
            item.confirmed_version_id or item.state == ChapterState.CONFIRMED
        )
        if not reasons and facts_changed and is_confirmed:
            reasons.append("前置确认事实发生变化")
        if not reasons and force and is_confirmed:
            reasons.append("前置章节已重新确认")

        if not reasons:
            continue

        unique_reasons = list(dict.fromkeys(reasons))
        item.needs_check = True
        if item.state not in {ChapterState.GENERATING, ChapterState.PLANNED}:
            item.state = ChapterState.OUTDATED
        affected.append(
            {
                "chapterId": item.id,
                "chapterIndex": item.chapter_index,
                "title": item.title,
                "reasons": unique_reasons,
            }
        )

    session.commit()
    return {
        "sourceChapterId": chapter.id,
        "sourceChapterIndex": chapter.chapter_index,
        "changedEntities": sorted(changed_entities),
        "changedThreads": sorted(changed_threads),
        "changedActions": sorted(a for a in changed_actions if a),
        "affectedChapters": affected,
        "forced": force,
    }
