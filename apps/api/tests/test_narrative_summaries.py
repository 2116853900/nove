from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.memory.summaries import SummaryService
from app.models import Chapter, ChapterVersion, NarrativeSummary


def test_confirmation_builds_provenance_and_outline_rollups(session: Session) -> None:
    chapter = session.get(Chapter, "c1")
    assert chapter is not None and chapter.current_version_id
    version = session.get(ChapterVersion, chapter.current_version_id)
    assert version is not None
    delta = {
        "events": [
            {
                "subjects": ["林远"],
                "action": "林远锁定信标坐标",
                "location": "观测台",
                "consequences": "舰队改变航向",
            }
        ],
        "entity_updates": [
            {
                "name": "林远",
                "facts": {"location": "观测台", "known_facts": ["信标坐标"]},
            }
        ],
        "plot_threads": [
            {
                "name": "信标来源",
                "status": "DEVELOPING",
                "latest": "坐标已锁定",
            }
        ],
    }

    result = SummaryService(session).update_from_confirmation(chapter, version, delta)

    item = session.scalar(
        select(NarrativeSummary).where(
            NarrativeSummary.scope_type == "chapter",
            NarrativeSummary.scope_id == chapter.id,
        )
    )
    assert item is not None
    assert item.version_id == version.id
    assert "锁定信标坐标" in item.summary
    assert item.canonical_facts[0]["sourceChapterId"] == chapter.id
    assert item.canonical_facts[0]["sourceVersionId"] == version.id
    assert item.canonical_facts[0]["confidence"] == 1.0
    assert item.open_loops[0]["name"] == "信标来源"
    assert result["chapterSummaries"] == 1
    assert result["rollupSummaries"] >= 1


def test_rebuild_novel_recreates_confirmed_chapter_summaries(session: Session) -> None:
    result = SummaryService(session).rebuild_novel("starfarer")
    summaries = session.scalars(
        select(NarrativeSummary).where(NarrativeSummary.novel_id == "starfarer")
    ).all()
    assert result["chapterSummaries"] >= 1
    assert any(item.scope_type == "chapter" for item in summaries)
