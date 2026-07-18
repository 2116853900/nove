from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import (
    AuditConfig,
    Chapter,
    ChapterVersion,
    Novel,
    OutlineNode,
    StoryEntity,
    Workspace,
    new_id,
)
from .services import AuditService


CHAPTER_SPLIT_RE = re.compile(
    r"(?m)^(?:#{1,3}\s*)?(第\s*[0-9一二三四五六七八九十百千零〇两]+\s*章[^\n]*|Chapter\s+\d+[^\n]*)$"
)


def split_manuscript(text: str) -> list[dict[str, str]]:
    """Split plain text / markdown into chapter title + body blocks."""
    raw = (text or "").replace("\r\n", "\n").strip()
    if not raw:
        return []

    matches = list(CHAPTER_SPLIT_RE.finditer(raw))
    if not matches:
        return [{"title": "第 1 章 · 导入正文", "content": raw}]

    chapters: list[dict[str, str]] = []
    # Optional preamble before first heading becomes chapter 0 only if substantial.
    if matches[0].start() > 40:
        preamble = raw[: matches[0].start()].strip()
        if preamble:
            chapters.append({"title": "序章 · 导入前言", "content": preamble})

    for index, match in enumerate(matches):
        title = match.group(0).lstrip("#").strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
        body = raw[start:end].strip()
        if not title.startswith("第") and not title.lower().startswith("chapter"):
            title = f"第 {index + 1} 章 · {title}"
        chapters.append({"title": title, "content": body or f"（{title} 正文为空）"})
    return chapters


class ImportExportService:
    def __init__(self, session: Session):
        self.session = session

    def import_text(
        self,
        *,
        title: str,
        text: str,
        genre: str = "导入",
        core_idea: str = "",
        confirm_all: bool = False,
    ) -> dict[str, Any]:
        from .auth import current_workspace_id

        ws_id = current_workspace_id()
        workspace = self.session.get(Workspace, ws_id)
        if workspace is None:
            workspace = Workspace(id=ws_id, name="本地工作区")
            self.session.add(workspace)
            self.session.flush()

        blocks = split_manuscript(text)
        if not blocks:
            raise ValueError("empty manuscript")

        novel = Novel(
            id=new_id(),
            workspace_id=workspace.id,
            title=title.strip() or "导入小说",
            genre=genre or "导入",
            core_idea=core_idea or f"从文稿导入，共 {len(blocks)} 章",
            creation_mode="import",
            planned_chapters=max(len(blocks), 20),
        )
        self.session.add(novel)
        self.session.flush()

        volume = OutlineNode(
            workspace_id=workspace.id,
            novel_id=novel.id,
            kind="volume",
            title="第一卷 · 导入",
            position=1,
        )
        self.session.add(volume)
        self.session.flush()
        arc = OutlineNode(
            workspace_id=workspace.id,
            novel_id=novel.id,
            parent_id=volume.id,
            kind="arc",
            title="导入正文",
            position=1,
        )
        self.session.add(arc)
        self.session.flush()

        created_chapters: list[str] = []
        for index, block in enumerate(blocks, start=1):
            short = block["title"]
            if "·" in short:
                short = short.split("·", 1)[-1].strip()
            node = OutlineNode(
                workspace_id=workspace.id,
                novel_id=novel.id,
                parent_id=arc.id,
                kind="chapter",
                title=block["title"] if block["title"].startswith("第") else f"第 {index} 章 · {short}",
                position=index,
                details={
                    "goal": "",
                    "must_events": [],
                    "forbidden_events": [],
                    "imported": True,
                },
            )
            self.session.add(node)
            self.session.flush()
            chapter = Chapter(
                workspace_id=workspace.id,
                novel_id=novel.id,
                outline_node_id=node.id,
                chapter_index=index,
                title=short or f"第 {index} 章",
                state="CONFIRMED" if confirm_all else "DRAFT",
                brief=node.details,
                target_words=max(1000, len(block["content"])),
            )
            self.session.add(chapter)
            self.session.flush()
            version = ChapterVersion(
                workspace_id=workspace.id,
                novel_id=novel.id,
                chapter_id=chapter.id,
                sequence=1,
                source="import",
                title=chapter.title,
                content=block["content"],
                content_json={"type": "doc", "text": block["content"]},
            )
            self.session.add(version)
            self.session.flush()
            chapter.current_version_id = version.id
            if confirm_all:
                chapter.confirmed_version_id = version.id
                chapter.memory_status = "NOT_INDEXED"
            created_chapters.append(chapter.id)

        self.session.add(
            AuditConfig(
                workspace_id=workspace.id,
                novel_id=novel.id,
                dimensions=AuditService.DEFAULT_DIMENSIONS,
            )
        )
        # Lightweight entity hints from first chapter names-like tokens are skipped;
        # user can fill bible manually. Optional: add placeholder note entity.
        self.session.add(
            StoryEntity(
                workspace_id=workspace.id,
                novel_id=novel.id,
                entity_type="character",
                name="（待整理）",
                summary="导入后请在故事圣经中完善人物",
                data={"role": "占位", "status": "未整理"},
            )
        )
        self.session.commit()
        return {
            "novelId": novel.id,
            "title": novel.title,
            "chapterCount": len(created_chapters),
            "chapterIds": created_chapters,
            "confirmed": confirm_all,
        }

    def export_markdown(self, novel: Novel, *, include_bible: bool = False) -> str:
        chapters = self.session.scalars(
            select(Chapter)
            .where(Chapter.novel_id == novel.id)
            .order_by(Chapter.chapter_index)
        ).all()
        lines = [
            f"# {novel.title}",
            "",
            f"> 题材：{novel.genre}  ·  视角：{novel.narrative_pov}",
            "",
        ]
        if novel.core_idea:
            lines.extend([f"**核心创意**：{novel.core_idea}", ""])

        for chapter in chapters:
            version = None
            if chapter.current_version_id:
                version = self.session.get(ChapterVersion, chapter.current_version_id)
            body = version.content if version else ""
            lines.append(f"## 第 {chapter.chapter_index} 章 · {chapter.title}")
            lines.append("")
            lines.append(body.strip() or "（空）")
            lines.append("")

        if include_bible:
            entities = self.session.scalars(
                select(StoryEntity).where(StoryEntity.novel_id == novel.id)
            ).all()
            if entities:
                lines.extend(["---", "", "# 故事圣经", ""])
                for entity in entities:
                    lines.append(f"### [{entity.entity_type}] {entity.name}")
                    lines.append(entity.summary or "")
                    lines.append("")

        return "\n".join(lines).strip() + "\n"

    def export_txt(self, novel: Novel, *, include_bible: bool = False) -> str:
        """Plain-text novel export with chapter headings (no Markdown syntax)."""
        chapters = self.session.scalars(
            select(Chapter)
            .where(Chapter.novel_id == novel.id)
            .order_by(Chapter.chapter_index)
        ).all()
        lines: list[str] = [
            novel.title,
            "",
            f"题材：{novel.genre}  ·  视角：{novel.narrative_pov}",
            "",
        ]
        if novel.core_idea:
            lines.extend([f"核心创意：{novel.core_idea}", ""])
        lines.append("=" * 40)
        lines.append("")

        for chapter in chapters:
            version = None
            if chapter.current_version_id:
                version = self.session.get(ChapterVersion, chapter.current_version_id)
            body = (version.content if version else "").strip() or "（空）"
            lines.append(f"第 {chapter.chapter_index} 章 · {chapter.title}")
            lines.append("-" * 40)
            lines.append(body)
            lines.append("")
            lines.append("")

        if include_bible:
            entities = self.session.scalars(
                select(StoryEntity).where(StoryEntity.novel_id == novel.id)
            ).all()
            if entities:
                lines.append("=" * 40)
                lines.append("故事圣经")
                lines.append("")
                for entity in entities:
                    lines.append(f"[{entity.entity_type}] {entity.name}")
                    if entity.summary:
                        lines.append(entity.summary)
                    lines.append("")

        return "\n".join(lines).rstrip() + "\n"

    def export_json_meta(self, novel: Novel) -> dict[str, Any]:
        chapters = self.session.scalars(
            select(Chapter)
            .where(Chapter.novel_id == novel.id)
            .order_by(Chapter.chapter_index)
        ).all()
        return {
            "id": novel.id,
            "title": novel.title,
            "genre": novel.genre,
            "coreIdea": novel.core_idea,
            "writingProfile": novel.writing_profile or {},
            "chapterCount": len(chapters),
            "totalWords": sum(
                len(
                    (
                        self.session.get(ChapterVersion, c.current_version_id).content
                        if c.current_version_id
                        and self.session.get(ChapterVersion, c.current_version_id)
                        else ""
                    )
                )
                for c in chapters
            ),
        }
