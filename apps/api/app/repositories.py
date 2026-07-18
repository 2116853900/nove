from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import current_workspace_id
from .models import Chapter, ChapterVersion, GenerationJob, Novel


class SqlAlchemyRepository:
    """SQLAlchemy adapter with workspace-scoped lookups."""

    def __init__(self, session: Session, workspace_id: str | None = None):
        self.session = session
        self.workspace_id = workspace_id or current_workspace_id()

    def _required(self, model: type, entity_id: str, label: str):
        entity = self.session.get(model, entity_id)
        if entity is None:
            raise HTTPException(status_code=404, detail=f"{label} not found")
        workspace_id = getattr(entity, "workspace_id", None)
        if workspace_id is not None and workspace_id != self.workspace_id:
            raise HTTPException(status_code=404, detail=f"{label} not found")
        return entity

    def get_novel(self, novel_id: str) -> Novel:
        novel = self.session.scalar(
            select(Novel).where(
                Novel.id == novel_id,
                Novel.workspace_id == self.workspace_id,
            )
        )
        if novel is None:
            raise HTTPException(status_code=404, detail="Novel not found")
        return novel

    def list_novels(self) -> list[Novel]:
        return list(
            self.session.scalars(
                select(Novel)
                .where(Novel.workspace_id == self.workspace_id)
                .order_by(Novel.updated_at.desc())
            ).all()
        )

    def get_chapter(self, chapter_id: str) -> Chapter:
        return self._required(Chapter, chapter_id, "Chapter")

    def get_version(self, version_id: str) -> ChapterVersion:
        return self._required(ChapterVersion, version_id, "Version")

    def get_job(self, job_id: str) -> GenerationJob:
        return self._required(GenerationJob, job_id, "Job")

    def commit(self) -> None:
        self.session.commit()
