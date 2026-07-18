from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Chapter, ChapterVersion, Novel, OutlineNode, StoryEntity
from app.seed import seed_demo_novel
from app.services_novel import delete_novel_cascade


def test_delete_novel_removes_cascade(session: Session) -> None:
    seed_demo_novel(session)
    novel = session.get(Novel, "starfarer")
    assert novel is not None
    assert session.scalar(select(func.count(Chapter.id)).where(Chapter.novel_id == "starfarer"))

    delete_novel_cascade(session, novel)
    session.commit()

    assert session.get(Novel, "starfarer") is None
    assert session.scalar(select(func.count(Chapter.id)).where(Chapter.novel_id == "starfarer")) == 0
    assert session.scalar(select(func.count(ChapterVersion.id)).where(ChapterVersion.novel_id == "starfarer")) == 0
    assert session.scalar(select(func.count(OutlineNode.id)).where(OutlineNode.novel_id == "starfarer")) == 0
    assert session.scalar(select(func.count(StoryEntity.id)).where(StoryEntity.novel_id == "starfarer")) == 0
