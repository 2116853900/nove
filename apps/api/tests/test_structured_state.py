from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Chapter,
    ChapterVersion,
    CharacterState,
    LocationState,
    NarrativeSummary,
    StoryEntity,
    StoryEvent,
)
from app.services import AuditService, ChapterService, MemoryService
from app.services_state import StateService


def test_apply_memory_delta_writes_character_state(session: Session) -> None:
    chapter = session.get(Chapter, "c2")
    assert chapter is not None
    entity = session.scalar(
        select(StoryEntity).where(
            StoryEntity.novel_id == chapter.novel_id,
            StoryEntity.entity_type == "character",
            StoryEntity.name == "林远",
        )
    )
    assert entity is not None

    counts = StateService(session).apply_from_memory_delta(
        chapter,
        {
            "entity_updates": [
                {
                    "name": "林远",
                    "entity_type": "character",
                    "summary": "更坚定",
                    "facts": {
                        "location": "观测台",
                        "alive": True,
                        "emotion": "决绝",
                        "known_facts": ["信标坠落坐标"],
                    },
                }
            ],
            "events": [
                {
                    "subjects": ["林远"],
                    "action": "锁定坐标",
                    "location": "观测台",
                }
            ],
        },
    )
    assert counts["characterStates"] >= 1
    state = session.scalar(
        select(CharacterState).where(
            CharacterState.entity_id == entity.id,
            CharacterState.chapter_id == chapter.id,
        )
    )
    assert state is not None
    assert state.location == "观测台"
    assert "信标坠落坐标" in (state.known_facts or [])


def test_memory_delta_merges_repeated_character_events_idempotently(
    session: Session,
) -> None:
    chapter = session.get(Chapter, "c2")
    assert chapter is not None
    entity = session.scalar(
        select(StoryEntity).where(
            StoryEntity.novel_id == chapter.novel_id,
            StoryEntity.entity_type == "character",
            StoryEntity.name == "林远",
        )
    )
    assert entity is not None
    delta = {
        "events": [
            {
                "subjects": ["林远"],
                "action": "进入观测台",
                "location": "观测台",
            },
            {
                "subjects": ["林远"],
                "action": "锁定信标坐标",
                "location": "观测台",
            },
            {
                "subjects": ["林远"],
                "action": "进入观测台",
                "location": "观测台",
            },
        ]
    }

    first = MemoryService(session)._apply_memory_delta(chapter, delta)
    second = MemoryService(session)._apply_memory_delta(chapter, delta)

    states = session.scalars(
        select(CharacterState).where(
            CharacterState.entity_id == entity.id,
            CharacterState.chapter_id == chapter.id,
        )
    ).all()
    events = session.scalars(
        select(StoryEvent).where(StoryEvent.chapter_id == chapter.id)
    ).all()
    assert first["characterStates"] == 1
    assert second["events"] == 0
    assert len(states) == 1
    assert states[0].location == "观测台"
    assert len(events) == 2


def test_continuity_flags_dead_character(session: Session) -> None:
    chapter = session.get(Chapter, "c2")
    assert chapter is not None
    entity = session.scalar(
        select(StoryEntity).where(
            StoryEntity.novel_id == chapter.novel_id,
            StoryEntity.name == "林远",
        )
    )
    assert entity is not None
    # State from chapter 1: dead
    c1 = session.get(Chapter, "c1")
    assert c1 is not None
    session.add(
        CharacterState(
            workspace_id="local",
            novel_id=chapter.novel_id,
            entity_id=entity.id,
            chapter_id=c1.id,
            chapter_index=1,
            alive=False,
            body_status="死亡",
            location="深空",
        )
    )
    session.commit()

    issues = StateService(session).continuity_issues_from_states(
        novel_id=chapter.novel_id,
        chapter_index=2,
        content="林远推开舱门，继续指挥舰队。",
    )
    assert any(i["type"] == "人物生死" for i in issues)


def test_destroyed_location_flagged(session: Session) -> None:
    chapter = session.get(Chapter, "c2")
    assert chapter is not None
    loc = session.scalar(
        select(StoryEntity).where(
            StoryEntity.novel_id == chapter.novel_id,
            StoryEntity.entity_type == "location",
        )
    )
    if loc is None:
        loc = StoryEntity(
            workspace_id="local",
            novel_id=chapter.novel_id,
            entity_type="location",
            name="观测台",
            summary="主观测台",
        )
        session.add(loc)
        session.commit()
    c1 = session.get(Chapter, "c1")
    assert c1 is not None
    session.add(
        LocationState(
            workspace_id="local",
            novel_id=chapter.novel_id,
            entity_id=loc.id,
            chapter_id=c1.id,
            chapter_index=1,
            condition="destroyed",
        )
    )
    session.commit()
    issues = StateService(session).continuity_issues_from_states(
        novel_id=chapter.novel_id,
        chapter_index=2,
        content=f"{loc.name}灯火通明，众人聚会。",
    )
    assert any(i["type"] == "地点状态" for i in issues)


def test_confirm_path_can_write_states(session: Session) -> None:
    chapter = session.get(Chapter, "c2")
    assert chapter is not None and chapter.current_version_id
    version = session.get(ChapterVersion, chapter.current_version_id)
    assert version is not None
    chapter.brief = {
        **(chapter.brief or {}),
        "must_events": ["锁定坐标"],
    }
    version.content = (version.content or "") + "\n\n林远在观测台锁定坐标。"
    session.commit()
    result = MemoryService(session).commit_confirmed_memory(chapter, version)
    assert "committed" in result


def test_audit_blocks_forbidden_event(session: Session) -> None:
    chapter = session.get(Chapter, "c2")
    assert chapter is not None
    chapter.brief = {**(chapter.brief or {}), "forbidden_events": ["提前引爆信标"]}
    version = ChapterService(session).create_version(
        chapter,
        content="林远决定提前引爆信标，火光照亮观测台。" * 30,
        title=chapter.title,
        source="user",
        base_version_id=chapter.current_version_id,
    )

    audit = AuditService(session).audit(chapter, version)

    assert audit.fatal_issues
    assert any(item["type"] == "禁止事件" for item in audit.issues)


def test_audit_uses_canonical_fact_provenance(session: Session) -> None:
    chapter = session.get(Chapter, "c2")
    c1 = session.get(Chapter, "c1")
    assert chapter is not None and c1 is not None and c1.confirmed_version_id
    session.add(
        NarrativeSummary(
            workspace_id=chapter.workspace_id,
            novel_id=chapter.novel_id,
            scope_type="chapter",
            scope_id=c1.id,
            chapter_id=c1.id,
            version_id=c1.confirmed_version_id,
            start_chapter_index=1,
            end_chapter_index=1,
            summary="林远已经死亡。",
            canonical_facts=[
                {
                    "fact": "林远.alive=False",
                    "kind": "entity_state",
                    "sourceChapterId": c1.id,
                    "sourceVersionId": c1.confirmed_version_id,
                    "confidence": 1.0,
                }
            ],
        )
    )
    session.commit()
    version = ChapterService(session).create_version(
        chapter,
        content="林远推开舱门，继续指挥舰队。" * 30,
        title=chapter.title,
        source="user",
        base_version_id=chapter.current_version_id,
    )

    audit = AuditService(session).audit(chapter, version)

    issue = next(item for item in audit.issues if item["type"] == "权威事实冲突")
    assert issue["severity"] == "fatal"
    assert c1.id in issue["conflictsWith"]
    assert c1.confirmed_version_id in issue["conflictsWith"]
