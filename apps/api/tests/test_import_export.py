from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.import_export import ImportExportService, split_manuscript
from app.models import Chapter, Novel
from app.services_relations import NovelAuditService, RelationService


SAMPLE = """第 1 章 · 开端

林远站在甲板上。

第 2 章 · 风暴

风浪打湿了甲板。
"""


def test_split_manuscript() -> None:
    blocks = split_manuscript(SAMPLE)
    assert len(blocks) == 2
    assert "开端" in blocks[0]["title"]
    assert "林远" in blocks[0]["content"]


def test_import_creates_chapters(session: Session) -> None:
    result = ImportExportService(session).import_text(
        title="导入测试",
        text=SAMPLE,
        genre="科幻",
    )
    assert result["chapterCount"] == 2
    novel = session.get(Novel, result["novelId"])
    assert novel is not None
    chapters = session.scalars(
        select(Chapter).where(Chapter.novel_id == novel.id).order_by(Chapter.chapter_index)
    ).all()
    assert len(chapters) == 2
    assert chapters[0].chapter_index == 1


def test_export_markdown_contains_chapters(session: Session) -> None:
    result = ImportExportService(session).import_text(title="导出书", text=SAMPLE)
    novel = session.get(Novel, result["novelId"])
    assert novel is not None
    md = ImportExportService(session).export_markdown(novel)
    assert "# 导出书" in md
    assert "第 1 章" in md
    assert "林远" in md


def test_export_txt_is_plain(session: Session) -> None:
    result = ImportExportService(session).import_text(title="纯文本书", text=SAMPLE)
    novel = session.get(Novel, result["novelId"])
    assert novel is not None
    txt = ImportExportService(session).export_txt(novel)
    assert "纯文本书" in txt
    assert "第 1 章" in txt
    assert "林远" in txt
    assert "##" not in txt
    assert "**" not in txt


def test_relations_and_scan(session: Session) -> None:
    # Use seed novel
    rel = RelationService(session)
    from app.models import StoryEntity

    entity = session.scalar(
        select(StoryEntity).where(
            StoryEntity.novel_id == "starfarer",
            StoryEntity.name == "林远",
        )
    )
    assert entity is not None
    rel.set_relations(
        entity.id,
        [{"to": "苏晚", "type": "同僚", "note": "信任裂痕"}],
    )
    edges = rel.list_for_novel("starfarer")
    assert any(e["toName"] == "苏晚" for e in edges)

    scan = NovelAuditService(session).scan("starfarer")
    assert "issueCount" in scan
    assert scan["scannedChapters"] >= 1
