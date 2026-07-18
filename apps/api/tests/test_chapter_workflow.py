from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import VersionConflictError
from app.models import ChapterAudit, ChapterVersion, MemoryChunk
from app.services import AuditService, ChapterService, GenerationService, MemoryService


def test_autosave_rejects_stale_base_version(session: Session) -> None:
    chapter = session.get(__import__("app.models", fromlist=["Chapter"]).Chapter, "c1")
    assert chapter is not None
    original = chapter.current_version_id

    saved = ChapterService(session).create_version(
        chapter,
        content="作者刚刚保存的新正文",
        title=chapter.title,
        source="user",
        base_version_id=original,
    )
    assert chapter.current_version_id == saved.id

    with pytest.raises(VersionConflictError):
        ChapterService(session).create_version(
            chapter,
            content="从旧页面发来的正文",
            title=chapter.title,
            source="user",
            base_version_id=original,
        )


def test_autosave_identical_content_reuses_current_version(session: Session) -> None:
    from app.models import Chapter

    chapter = session.get(Chapter, "c1")
    assert chapter is not None and chapter.current_version_id
    current = session.get(ChapterVersion, chapter.current_version_id)
    assert current is not None
    before_count = len(
        session.scalars(
            select(ChapterVersion).where(ChapterVersion.chapter_id == chapter.id)
        ).all()
    )

    saved = ChapterService(session).create_version(
        chapter,
        content=current.content,
        title=current.title,
        source="user",
        base_version_id=current.id,
        locked_ranges=current.locked_ranges,
    )
    after_count = len(
        session.scalars(
            select(ChapterVersion).where(ChapterVersion.chapter_id == chapter.id)
        ).all()
    )

    assert saved.id == current.id
    assert after_count == before_count


def test_generation_creates_candidate_without_overwriting_current(session: Session) -> None:
    from app.models import Chapter

    chapter = session.get(Chapter, "c1")
    assert chapter is not None
    current_id = chapter.current_version_id
    job = GenerationService(session).create_job(chapter, current_id, "GENERATE_CHAPTER")

    GenerationService(session).run_job(job.id, auto_audit=True)
    session.refresh(job)
    session.refresh(chapter)

    assert job.state == "COMPLETED"
    assert chapter.current_version_id == current_id
    candidate = session.get(ChapterVersion, job.result["versionId"])
    assert candidate is not None
    assert candidate.base_version_id == current_id
    streamed = "".join(
        event.get("delta", "") for event in job.events if event.get("type") == "content_delta"
    )
    assert streamed == candidate.content
    assert chapter.latest_score == 88
    assert session.scalar(
        select(ChapterAudit).where(ChapterAudit.version_id == candidate.id)
    ) is not None


def test_rewrite_uses_current_content_without_overwriting_current(session: Session) -> None:
    from app.models import Chapter

    class RecordingWritingModel:
        name = "recording-writer"

        def __init__(self) -> None:
            self.existing_content = ""

        def generate(self, *, title, brief, existing_content, on_delta=None):
            self.existing_content = existing_content
            content = "这是基于原章生成的重写候选。" * 80
            if on_delta is not None:
                on_delta(content)
            return content

    chapter = session.get(Chapter, "c1")
    assert chapter is not None and chapter.current_version_id
    current_id = chapter.current_version_id
    current = session.get(ChapterVersion, current_id)
    assert current is not None
    model = RecordingWritingModel()
    service = GenerationService(session, model=model)
    job = service.create_job(chapter, current_id, "REWRITE_CHAPTER")

    service.run_job(job.id, auto_audit=False)
    session.refresh(job)
    session.refresh(chapter)

    assert job.state == "COMPLETED"
    assert model.existing_content == current.content
    assert chapter.current_version_id == current_id
    candidate = session.get(ChapterVersion, job.result["versionId"])
    assert candidate is not None
    assert candidate.source == "rewrite"
    assert candidate.base_version_id == current_id


def test_stale_generation_does_not_overwrite_chapter_metadata(session: Session) -> None:
    from app.models import Chapter

    chapter = session.get(Chapter, "c1")
    assert chapter is not None
    original = chapter.current_version_id
    job = GenerationService(session).create_job(chapter, original, "GENERATE_CHAPTER")
    ChapterService(session).create_version(
        chapter,
        content="用户在生成期间保存的新正文",
        title=chapter.title,
        source="user",
        base_version_id=original,
    )
    latest_id = chapter.current_version_id
    latest_score = chapter.latest_score

    GenerationService(session).run_job(job.id, auto_audit=True)
    session.refresh(chapter)
    session.refresh(job)

    assert job.result["stale"] is True
    assert chapter.current_version_id == latest_id
    assert chapter.latest_score == latest_score
    assert chapter.state == "DRAFT"


def test_audit_fatal_issue_forces_rewrite(session: Session) -> None:
    from app.models import Chapter

    chapter = session.get(Chapter, "c1")
    assert chapter is not None
    chapter.needs_check = True
    version = ChapterService(session).create_version(
        chapter,
        content="他早就知道信标来自泽塔星。锁定信标坐标。" * 30,
        title=chapter.title,
        source="user",
        base_version_id=chapter.current_version_id,
    )
    audit = AuditService(session).audit(chapter, version)

    assert audit.decision == "REWRITE"
    assert audit.fatal_issues
    assert any(item["type"] == "知识边界" for item in audit.issues)
    assert chapter.needs_check is False


def test_restore_switches_current_without_creating_version(session: Session) -> None:
    from app.models import Chapter

    chapter = session.get(Chapter, "c1")
    assert chapter is not None and chapter.current_version_id
    target = session.get(ChapterVersion, chapter.current_version_id)
    assert target is not None
    newer = ChapterService(session).create_version(
        chapter,
        content="后续版本正文",
        title=chapter.title,
        source="user",
        base_version_id=target.id,
    )
    assert chapter.current_version_id == newer.id
    before_count = len(
        session.scalars(
            select(ChapterVersion).where(ChapterVersion.chapter_id == chapter.id)
        ).all()
    )

    restored = ChapterService(session).restore(chapter, target, "尚未保存的当前内容")
    after_count = len(
        session.scalars(
            select(ChapterVersion).where(ChapterVersion.chapter_id == chapter.id)
        ).all()
    )

    assert after_count == before_count
    assert restored.id == target.id
    assert chapter.current_version_id == target.id


def test_candidate_must_be_accepted_before_becoming_current(session: Session) -> None:
    from app.models import Chapter

    chapter = session.get(Chapter, "c1")
    assert chapter is not None
    current_id = chapter.current_version_id
    job = GenerationService(session).create_job(chapter, current_id, "GENERATE_CHAPTER")
    GenerationService(session).run_job(job.id, auto_audit=True)
    candidate = session.get(ChapterVersion, job.result["versionId"])
    assert candidate is not None

    ChapterService(session).accept_candidate(chapter, candidate)

    assert chapter.current_version_id == candidate.id
    assert chapter.latest_score == candidate.audit_score


def test_delete_version_removes_related_data_and_repairs_lineage(session: Session) -> None:
    from app.models import Chapter

    chapter = session.get(Chapter, "c1")
    assert chapter is not None and chapter.current_version_id
    current_id = chapter.current_version_id
    removable = ChapterService(session).create_version(
        chapter,
        content="待删除候选正文" * 100,
        title=chapter.title,
        source="rewrite",
        base_version_id=current_id,
        make_current=False,
    )
    dependent = ChapterService(session).create_version(
        chapter,
        content="依赖版本正文" * 100,
        title=chapter.title,
        source="rewrite",
        base_version_id=removable.id,
        make_current=False,
    )
    audit = AuditService(session).audit(chapter, removable, update_chapter=False)
    memory = MemoryChunk(
        workspace_id=chapter.workspace_id,
        novel_id=chapter.novel_id,
        chapter_id=chapter.id,
        version_id=removable.id,
        chunk_index=0,
        content="待删除索引",
    )
    session.add(memory)
    session.commit()

    ChapterService(session).delete_version(chapter, removable)
    session.refresh(dependent)

    assert session.get(ChapterVersion, removable.id) is None
    assert session.get(ChapterAudit, audit.id) is None
    assert session.get(MemoryChunk, memory.id) is None
    assert dependent.base_version_id == current_id


def test_delete_current_version_is_rejected(session: Session) -> None:
    from app.models import Chapter

    chapter = session.get(Chapter, "c1")
    assert chapter is not None and chapter.current_version_id
    current = session.get(ChapterVersion, chapter.current_version_id)
    assert current is not None

    with pytest.raises(VersionConflictError):
        ChapterService(session).delete_version(chapter, current)


def test_confirmed_version_creates_memory_chunks(session: Session) -> None:
    from app.models import Chapter

    chapter = session.get(Chapter, "c1")
    assert chapter is not None and chapter.current_version_id
    version = session.get(ChapterVersion, chapter.current_version_id)
    assert version is not None

    chunks = MemoryService(session).index_confirmed_version(chapter, version)

    assert chunks
    assert all(item.version_id == version.id for item in chunks)
    assert session.scalar(select(MemoryChunk).where(MemoryChunk.version_id == version.id))
    assert chapter.memory_status == "INDEXED"


def test_rewrite_audit_detects_removed_locked_content(session: Session) -> None:
    from app.models import Chapter

    chapter = session.get(Chapter, "c1")
    assert chapter is not None
    base = session.get(ChapterVersion, chapter.current_version_id)
    assert base is not None
    locked = base.content[:24]
    candidate = ChapterService(session).create_version(
        chapter,
        content="完全不同的重写正文" * 80,
        title=chapter.title,
        source="rewrite",
        base_version_id=chapter.current_version_id,
        make_current=False,
    )

    audit = AuditService(session).audit(
        chapter, candidate, update_chapter=False, protected_texts=[locked]
    )

    assert audit.decision == "REWRITE"
    assert any(item["type"] == "锁定内容" for item in audit.fatal_issues)
