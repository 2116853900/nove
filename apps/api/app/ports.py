from __future__ import annotations

from typing import Callable, Protocol

from .models import Chapter, ChapterVersion, GenerationJob, Novel


class NoveRepository(Protocol):
    def get_novel(self, novel_id: str) -> Novel: ...

    def get_chapter(self, chapter_id: str) -> Chapter: ...

    def get_version(self, version_id: str) -> ChapterVersion: ...

    def get_job(self, job_id: str) -> GenerationJob: ...

    def commit(self) -> None: ...


class WritingModel(Protocol):
    name: str

    def generate(
        self,
        *,
        title: str,
        brief: dict,
        existing_content: str,
        on_delta: Callable[[str], None] | None = None,
    ) -> str: ...
