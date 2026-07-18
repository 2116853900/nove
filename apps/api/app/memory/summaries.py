from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (
    Chapter,
    ChapterVersion,
    NarrativeSummary,
    OutlineNode,
    StoryEvent,
)
from .context_budget import estimate_text_tokens, truncate_text


def summary_payload(item: NarrativeSummary) -> dict[str, Any]:
    return {
        "scopeType": item.scope_type,
        "scopeId": item.scope_id,
        "summary": item.summary,
        "canonicalFacts": item.canonical_facts or [],
        "openLoops": item.open_loops or [],
        "entityNames": item.entity_names or [],
        "sourceChapterIds": item.source_chapter_ids or [],
        "startChapterIndex": item.start_chapter_index,
        "endChapterIndex": item.end_chapter_index,
        "tokenCount": item.token_count,
    }


class SummaryService:
    def __init__(self, session: Session):
        self.session = session

    def get(self, novel_id: str, scope_type: str, scope_id: str) -> NarrativeSummary | None:
        return self.session.scalar(
            select(NarrativeSummary).where(
                NarrativeSummary.novel_id == novel_id,
                NarrativeSummary.scope_type == scope_type,
                NarrativeSummary.scope_id == scope_id,
            )
        )

    def update_from_confirmation(
        self,
        chapter: Chapter,
        version: ChapterVersion,
        delta: dict[str, Any],
        *,
        rebuild_rollups: bool = True,
    ) -> dict[str, int]:
        summary = self._chapter_summary(chapter, version, delta)
        self._upsert(
            chapter,
            scope_type="chapter",
            scope_id=chapter.id,
            chapter_id=chapter.id,
            version_id=version.id,
            start_index=chapter.chapter_index,
            end_index=chapter.chapter_index,
            **summary,
        )
        self.session.flush()
        rollups = 0
        if rebuild_rollups:
            for node in self._outline_ancestors(chapter):
                if node.kind not in {"arc", "volume"}:
                    continue
                if self._rebuild_outline_summary(chapter.novel_id, node):
                    rollups += 1
        self.session.commit()
        return {"chapterSummaries": 1, "rollupSummaries": rollups}

    def rebuild_novel(self, novel_id: str) -> dict[str, int]:
        chapters = self.session.scalars(
            select(Chapter)
            .where(
                Chapter.novel_id == novel_id,
                Chapter.confirmed_version_id.is_not(None),
            )
            .order_by(Chapter.chapter_index)
        ).all()
        for chapter in chapters:
            version = self.session.get(ChapterVersion, chapter.confirmed_version_id)
            if version is None:
                continue
            events = self.session.scalars(
                select(StoryEvent)
                .where(
                    StoryEvent.chapter_id == chapter.id,
                    StoryEvent.source_outline_node_id.is_(None),
                )
                .order_by(StoryEvent.sequence)
            ).all()
            delta = {
                "events": [
                    {
                        "subjects": item.subjects or [],
                        "action": item.action,
                        "location": item.location,
                        "consequences": item.consequences,
                    }
                    for item in events
                ]
            }
            self.update_from_confirmation(
                chapter, version, delta, rebuild_rollups=False
            )

        nodes = self.session.scalars(
            select(OutlineNode).where(
                OutlineNode.novel_id == novel_id,
                OutlineNode.kind.in_(["arc", "volume"]),
            )
        ).all()
        rollups = sum(1 for node in nodes if self._rebuild_outline_summary(novel_id, node))
        self.session.commit()
        return {"chapterSummaries": len(chapters), "rollupSummaries": rollups}

    def _chapter_summary(
        self, chapter: Chapter, version: ChapterVersion, delta: dict[str, Any]
    ) -> dict[str, Any]:
        events = [item for item in (delta.get("events") or []) if isinstance(item, dict)]
        updates = [
            item for item in (delta.get("entity_updates") or []) if isinstance(item, dict)
        ]
        threads = [
            item for item in (delta.get("plot_threads") or []) if isinstance(item, dict)
        ]
        actions = [str(item.get("action") or "").strip() for item in events]
        actions = [item for item in actions if item]
        consequences = [
            str(item.get("consequences") or "").strip() for item in events
        ]
        consequences = [item for item in consequences if item]
        goal = str((chapter.brief or {}).get("goal") or "").strip()
        parts = [f"第 {chapter.chapter_index} 章《{chapter.title}》"]
        if goal:
            parts.append(f"目标：{goal}")
        if actions:
            parts.append("关键事件：" + "；".join(actions[:12]))
        if consequences:
            parts.append("结果：" + "；".join(consequences[:8]))
        if len(parts) == 1:
            body = version.content.strip()
            parts.append("正文摘要线索：" + body[:360] + ("…" if len(body) > 720 else "") + body[-360:])
        text = truncate_text("。".join(parts), 1200)

        entity_names = _dedupe(
            [str(name) for item in events for name in (item.get("subjects") or [])]
            + [str(item.get("name") or "") for item in updates]
        )[:80]
        facts: list[dict[str, Any]] = []
        for item in events:
            action = str(item.get("action") or "").strip()
            if action:
                facts.append(
                    self._fact(
                        action,
                        chapter,
                        version,
                        kind="event",
                    )
                )
        for item in updates:
            name = str(item.get("name") or "").strip()
            raw_facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
            for key, value in raw_facts.items():
                facts.append(
                    self._fact(
                        f"{name}.{key}={value}",
                        chapter,
                        version,
                        kind="entity_state",
                    )
                )
        loops = [
            {
                "name": str(item.get("name") or ""),
                "status": str(item.get("status") or "DEVELOPING"),
                "latest": str(item.get("latest") or ""),
                "sourceChapterId": chapter.id,
            }
            for item in threads
            if str(item.get("status") or "") not in {"PAID_OFF", "ABANDONED"}
        ]
        return {
            "summary": text,
            "canonical_facts": _dedupe_dicts(facts, "fact")[:120],
            "open_loops": _dedupe_dicts(loops, "name")[:60],
            "entity_names": entity_names,
            "source_chapter_ids": [chapter.id],
        }

    @staticmethod
    def _fact(
        fact: str,
        chapter: Chapter,
        version: ChapterVersion,
        *,
        kind: str,
    ) -> dict[str, Any]:
        return {
            "fact": fact,
            "kind": kind,
            "sourceChapterId": chapter.id,
            "sourceVersionId": version.id,
            "confidence": 1.0,
        }

    def _outline_ancestors(self, chapter: Chapter) -> list[OutlineNode]:
        result: list[OutlineNode] = []
        node = self.session.get(OutlineNode, chapter.outline_node_id) if chapter.outline_node_id else None
        seen: set[str] = set()
        while node is not None and node.id not in seen:
            seen.add(node.id)
            result.append(node)
            node = self.session.get(OutlineNode, node.parent_id) if node.parent_id else None
        return result

    def _rebuild_outline_summary(self, novel_id: str, node: OutlineNode) -> bool:
        chapter_ids = self._descendant_chapter_ids(novel_id, node.id)
        if not chapter_ids:
            return False
        summaries = self.session.scalars(
            select(NarrativeSummary)
            .where(
                NarrativeSummary.novel_id == novel_id,
                NarrativeSummary.scope_type == "chapter",
                NarrativeSummary.chapter_id.in_(chapter_ids),
            )
            .order_by(NarrativeSummary.start_chapter_index)
        ).all()
        if not summaries:
            return False
        combined = "\n".join(item.summary for item in summaries if item.summary)
        token_limit = 2400 if node.kind == "arc" else 3600
        if estimate_text_tokens(combined) > token_limit:
            head = truncate_text(combined, token_limit // 3)
            tail_source = combined[max(0, len(combined) - token_limit * 3) :]
            tail = truncate_text(tail_source, token_limit - estimate_text_tokens(head) - 20)
            combined = head + "\n…\n" + tail
        facts = _dedupe_dicts(
            [fact for item in summaries for fact in (item.canonical_facts or [])],
            "fact",
        )[:200]
        loops = _latest_loops(
            [loop for item in summaries for loop in (item.open_loops or [])]
        )[:100]
        entities = _dedupe(
            [name for item in summaries for name in (item.entity_names or [])]
        )[:150]
        self._upsert(
            summaries[0],
            scope_type=node.kind,
            scope_id=node.id,
            chapter_id=None,
            version_id=None,
            start_index=summaries[0].start_chapter_index,
            end_index=summaries[-1].end_chapter_index,
            summary=combined,
            canonical_facts=facts,
            open_loops=loops,
            entity_names=entities,
            source_chapter_ids=[item.chapter_id for item in summaries if item.chapter_id],
        )
        return True

    def _descendant_chapter_ids(self, novel_id: str, root_id: str) -> list[str]:
        nodes = self.session.scalars(
            select(OutlineNode).where(OutlineNode.novel_id == novel_id)
        ).all()
        children: dict[str, list[OutlineNode]] = {}
        for node in nodes:
            if node.parent_id:
                children.setdefault(node.parent_id, []).append(node)
        descendant_ids: set[str] = set()
        stack = [root_id]
        while stack:
            parent_id = stack.pop()
            for child in children.get(parent_id, []):
                descendant_ids.add(child.id)
                stack.append(child.id)
        return list(
            self.session.scalars(
                select(Chapter.id).where(Chapter.outline_node_id.in_(descendant_ids))
            ).all()
        )

    def _upsert(
        self,
        owner: Chapter | NarrativeSummary,
        *,
        scope_type: str,
        scope_id: str,
        chapter_id: str | None,
        version_id: str | None,
        start_index: int,
        end_index: int,
        summary: str,
        canonical_facts: list[dict[str, Any]],
        open_loops: list[dict[str, Any]],
        entity_names: list[str],
        source_chapter_ids: list[str],
    ) -> NarrativeSummary:
        novel_id = owner.novel_id
        workspace_id = owner.workspace_id
        item = self.get(novel_id, scope_type, scope_id)
        if item is None:
            item = NarrativeSummary(
                workspace_id=workspace_id,
                novel_id=novel_id,
                scope_type=scope_type,
                scope_id=scope_id,
            )
            self.session.add(item)
        item.chapter_id = chapter_id
        item.version_id = version_id
        item.start_chapter_index = start_index
        item.end_chapter_index = end_index
        item.summary = summary
        item.canonical_facts = canonical_facts
        item.open_loops = open_loops
        item.entity_names = entity_names
        item.source_chapter_ids = source_chapter_ids
        item.token_count = estimate_text_tokens(summary)
        return item


def _dedupe(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _dedupe_dicts(values: Iterable[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        marker = str(value.get(key) or "").strip()
        if not marker or marker in seen:
            continue
        seen.add(marker)
        result.append(value)
    return result


def _latest_loops(values: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for value in values:
        name = str(value.get("name") or "").strip()
        if not name:
            continue
        status = str(value.get("status") or "DEVELOPING")
        if status in {"PAID_OFF", "ABANDONED"}:
            latest.pop(name, None)
        else:
            latest[name] = value
    return list(latest.values())
