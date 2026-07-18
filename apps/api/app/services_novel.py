from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    AgentCallLog,
    AuditConfig,
    Chapter,
    ChapterAudit,
    ChapterVersion,
    CharacterState,
    GenerationJob,
    LocationState,
    MemoryChunk,
    ModelConfig,
    Novel,
    NovelRule,
    OutlineNode,
    PlotThread,
    SkillRun,
    StoryBeat,
    StoryEntity,
    StoryEvent,
)


def delete_novel_cascade(session: Session, novel: Novel) -> None:
    """Remove a novel and all dependent rows (FK-safe order)."""
    novel_id = novel.id
    chapter_ids = select(Chapter.id).where(Chapter.novel_id == novel_id)
    entity_ids = select(StoryEntity.id).where(StoryEntity.novel_id == novel_id)

    # Children of chapters / entities first
    for model, condition in [
        (CharacterState, CharacterState.novel_id == novel_id),
        (LocationState, LocationState.novel_id == novel_id),
        (MemoryChunk, MemoryChunk.novel_id == novel_id),
        (ChapterAudit, ChapterAudit.novel_id == novel_id),
        (GenerationJob, GenerationJob.novel_id == novel_id),
        (AgentCallLog, AgentCallLog.novel_id == novel_id),
        (SkillRun, SkillRun.novel_id == novel_id),
        (ChapterVersion, ChapterVersion.novel_id == novel_id),
        (StoryEvent, StoryEvent.novel_id == novel_id),
        (PlotThread, PlotThread.novel_id == novel_id),
        (StoryBeat, StoryBeat.novel_id == novel_id),
        (Chapter, Chapter.novel_id == novel_id),
        (StoryEntity, StoryEntity.novel_id == novel_id),
        (NovelRule, NovelRule.novel_id == novel_id),
        (ModelConfig, ModelConfig.novel_id == novel_id),
        (AuditConfig, AuditConfig.novel_id == novel_id),
    ]:
        session.query(model).filter(condition).delete(synchronize_session=False)

    # Outline tree: delete leaves first (scenes → chapters → arcs → volumes)
    nodes = session.scalars(
        select(OutlineNode).where(OutlineNode.novel_id == novel_id)
    ).all()
    by_parent: dict[str | None, list[OutlineNode]] = {}
    for node in nodes:
        by_parent.setdefault(node.parent_id, []).append(node)

    ordered: list[OutlineNode] = []

    def walk(parent_id: str | None) -> None:
        for child in by_parent.get(parent_id, []):
            walk(child.id)
            ordered.append(child)

    walk(None)
    for node in ordered:
        session.delete(node)

    session.delete(novel)
