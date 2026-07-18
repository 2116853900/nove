from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import StoryEntity
from .services_state import StateService


class RelationService:
    """Character relations stored on entity.data['relations'] as a simple list."""

    def __init__(self, session: Session):
        self.session = session

    def list_for_novel(self, novel_id: str) -> list[dict[str, Any]]:
        entities = self.session.scalars(
            select(StoryEntity).where(
                StoryEntity.novel_id == novel_id,
                StoryEntity.entity_type == "character",
            )
        ).all()
        edges: list[dict[str, Any]] = []
        for entity in entities:
            relations = (entity.data or {}).get("relations") or []
            if not isinstance(relations, list):
                continue
            for item in relations:
                if not isinstance(item, dict):
                    continue
                edges.append(
                    {
                        "fromId": entity.id,
                        "fromName": entity.name,
                        "toName": str(item.get("to") or item.get("name") or ""),
                        "type": str(item.get("type") or item.get("relation") or "关系"),
                        "note": str(item.get("note") or ""),
                        "sinceChapter": item.get("sinceChapter") or item.get("since"),
                    }
                )
        return edges

    def set_relations(
        self, entity_id: str, relations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        entity = self.session.get(StoryEntity, entity_id)
        if entity is None:
            raise ValueError("entity not found")
        if entity.entity_type != "character":
            raise ValueError("relations only supported for characters")
        cleaned = []
        for item in relations:
            if not isinstance(item, dict):
                continue
            name = str(item.get("to") or item.get("name") or "").strip()
            if not name:
                continue
            cleaned.append(
                {
                    "to": name,
                    "type": str(item.get("type") or item.get("relation") or "关系"),
                    "note": str(item.get("note") or ""),
                    "sinceChapter": item.get("sinceChapter") or item.get("since"),
                }
            )
        data = dict(entity.data or {})
        data["relations"] = cleaned
        entity.data = data
        self.session.commit()
        return {"entityId": entity.id, "relations": cleaned}


class NovelAuditService:
    """Whole-novel lightweight continuity scan (P1)."""

    def __init__(self, session: Session):
        self.session = session

    def scan(self, novel_id: str) -> dict[str, Any]:
        from .models import Chapter, ChapterVersion, PlotThread

        chapters = self.session.scalars(
            select(Chapter)
            .where(Chapter.novel_id == novel_id)
            .order_by(Chapter.chapter_index)
        ).all()
        issues: list[dict[str, Any]] = []
        state_svc = StateService(self.session)

        for chapter in chapters:
            if not chapter.current_version_id:
                continue
            version = self.session.get(ChapterVersion, chapter.current_version_id)
            if version is None or not version.content:
                continue
            content = version.content
            state_issues = state_svc.continuity_issues_from_states(
                novel_id=novel_id,
                chapter_index=chapter.chapter_index,
                content=content,
            )
            for item in state_issues:
                issues.append(
                    {
                        **item,
                        "chapterId": chapter.id,
                        "chapterIndex": chapter.chapter_index,
                        "chapterTitle": chapter.title,
                    }
                )
            if "早就知道" in content:
                issues.append(
                    {
                        "severity": "fatal",
                        "type": "知识边界",
                        "evidence": "早就知道",
                        "reason": "全书扫描发现知识泄漏用语",
                        "chapterId": chapter.id,
                        "chapterIndex": chapter.chapter_index,
                        "chapterTitle": chapter.title,
                    }
                )

        threads = self.session.scalars(
            select(PlotThread).where(PlotThread.novel_id == novel_id)
        ).all()
        for thread in threads:
            if thread.status in {"PLANTED", "DEVELOPING"} and thread.importance == "高":
                issues.append(
                    {
                        "severity": "major",
                        "type": "伏笔遗漏",
                        "evidence": thread.name,
                        "reason": f"高重要度线索「{thread.name}」仍为 {thread.status}",
                        "chapterId": None,
                        "chapterIndex": None,
                        "chapterTitle": None,
                    }
                )

        # Characters never appearing in any chapter body
        entities = self.session.scalars(
            select(StoryEntity).where(
                StoryEntity.novel_id == novel_id,
                StoryEntity.entity_type == "character",
            )
        ).all()
        all_text = ""
        for chapter in chapters:
            if chapter.current_version_id:
                version = self.session.get(ChapterVersion, chapter.current_version_id)
                if version:
                    all_text += version.content or ""
        for entity in entities:
            if entity.name in {"（待整理）"}:
                continue
            if entity.name and entity.name not in all_text:
                issues.append(
                    {
                        "severity": "minor",
                        "type": "人物消失",
                        "evidence": entity.name,
                        "reason": f"人物「{entity.name}」未在任何章节正文出现",
                        "chapterId": None,
                        "chapterIndex": None,
                        "chapterTitle": None,
                    }
                )

        # Dedupe
        seen: set[tuple[str, str, str]] = set()
        unique: list[dict[str, Any]] = []
        for item in issues:
            key = (
                str(item.get("type") or ""),
                str(item.get("evidence") or "")[:80],
                str(item.get("chapterId") or ""),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)

        return {
            "novelId": novel_id,
            "scannedChapters": len(chapters),
            "issueCount": len(unique),
            "fatalCount": sum(1 for i in unique if i.get("severity") == "fatal"),
            "issues": unique,
        }
