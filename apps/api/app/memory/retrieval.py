from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Chapter, MemoryChunk, PlotThread, StoryEntity
from .embeddings import EmbeddingProvider, resolve_embedding
from .qdrant_store import QdrantVectorStore


@dataclass
class RetrievalHit:
    chunk: MemoryChunk
    score: float
    semantic: float
    entity: float
    plotline: float
    time_proximity: float
    importance: float

    def as_source(self) -> dict[str, str]:
        meta = self.chunk.metadata_json or {}
        label = self.chunk.summary or self.chunk.content[:80]
        chapter_index = meta.get("chapterIndex")
        if chapter_index is not None:
            label = f"第 {chapter_index} 章 · {label}"
        return {
            "type": "memory",
            "id": self.chunk.id,
            "label": label,
            "score": f"{self.score:.3f}",
        }


class HybridRetriever:
    """Hybrid ranking per system design §5.2 (works on SQLite via JSON vectors)."""

    def __init__(self, session: Session, provider: EmbeddingProvider | None = None):
        self.session = session
        self.provider = provider

    def search(
        self,
        *,
        novel_id: str,
        chapter: Chapter,
        query_text: str,
        entity_names: list[str] | None = None,
        plot_names: list[str] | None = None,
        limit: int = 6,
    ) -> list[RetrievalHit]:
        return self.search_many(
            novel_id=novel_id,
            chapter=chapter,
            query_texts=[query_text],
            entity_names=entity_names,
            plot_names=plot_names,
            limit=limit,
        )

    def search_many(
        self,
        *,
        novel_id: str,
        chapter: Chapter,
        query_texts: list[str],
        entity_names: list[str] | None = None,
        plot_names: list[str] | None = None,
        limit: int = 6,
    ) -> list[RetrievalHit]:
        provider = self.provider or resolve_embedding(self.session, novel_id)
        queries = list(dict.fromkeys(text.strip() for text in query_texts if text.strip()))
        if not queries:
            queries = [chapter.title]

        prior_chapter_ids = {
            item.id
            for item in self.session.scalars(
                select(Chapter).where(
                    Chapter.novel_id == novel_id,
                    Chapter.chapter_index < chapter.chapter_index,
                    Chapter.confirmed_version_id.is_not(None),
                )
            ).all()
        }
        chunks = self.session.scalars(
            select(MemoryChunk).where(
                MemoryChunk.novel_id == novel_id,
                MemoryChunk.index_status == "INDEXED",
            )
        ).all()
        chunks_by_id = {
            chunk.id: chunk
            for chunk in chunks
            if chunk.chapter_id in prior_chapter_ids
        }

        entities = entity_names or [
            e.name
            for e in self.session.scalars(
                select(StoryEntity).where(StoryEntity.novel_id == novel_id)
            ).all()
        ]
        plots = plot_names or [
            t.name
            for t in self.session.scalars(
                select(PlotThread).where(
                    PlotThread.novel_id == novel_id,
                    PlotThread.status.not_in(["PAID_OFF", "ABANDONED"]),
                )
            ).all()
        ]

        vector_store = QdrantVectorStore(self.session, provider.dimensions())
        candidates: dict[str, dict[str, Any]] = {}
        candidate_limit = max(24, limit * 5)
        for query_index, query in enumerate(queries):
            vector_hits = vector_store.search(
                provider.embed_query(query),
                workspace_id=chapter.workspace_id,
                novel_id=novel_id,
                prior_chapter_ids=prior_chapter_ids,
                model_id=provider.model_id,
                model_version=provider.version,
                limit=candidate_limit,
            )
            for rank, vector_hit in enumerate(vector_hits, start=1):
                state = candidates.setdefault(
                    vector_hit.chunk_id,
                    {"best": 0.0, "queries": set(), "rrf": 0.0},
                )
                state["best"] = max(float(state["best"]), vector_hit.score)
                state["queries"].add(query_index)
                state["rrf"] += 1.0 / (60 + rank)

        hits: list[RetrievalHit] = []
        for chunk_id, candidate in candidates.items():
            chunk = chunks_by_id.get(chunk_id)
            if chunk is None:
                continue
            meta = chunk.metadata_json or {}
            coverage = len(candidate["queries"]) / len(queries)
            rrf_bonus = min(1.0, float(candidate["rrf"]) * 12)
            semantic = max(
                0.0,
                float(candidate["best"]) * 0.80
                + coverage * 0.12
                + rrf_bonus * 0.08,
            )

            entity_score = _entity_match(chunk.content, entities)
            plot_score = _entity_match(chunk.content, plots)
            chapter_index = int(meta.get("chapterIndex") or 0)
            distance = max(1, chapter.chapter_index - chapter_index)
            time_score = 1.0 / distance
            importance = float(meta.get("importance") or 0.5)
            importance = max(0.0, min(1.0, importance))

            final = (
                semantic * 0.45
                + entity_score * 0.20
                + plot_score * 0.15
                + time_score * 0.10
                + importance * 0.10
            )
            hits.append(
                RetrievalHit(
                    chunk=chunk,
                    score=final,
                    semantic=semantic,
                    entity=entity_score,
                    plotline=plot_score,
                    time_proximity=time_score,
                    importance=importance,
                )
            )

        hits.sort(key=lambda item: item.score, reverse=True)
        return _diversify(hits, limit)


def build_query_text(chapter: Chapter, brief: dict[str, Any] | None = None) -> str:
    brief = brief or chapter.brief or {}
    parts = [
        chapter.title,
        str(brief.get("goal") or ""),
        str(brief.get("conflict") or ""),
        " ".join(brief.get("must_events") or []),
        " ".join(brief.get("characters") or []),
        " ".join(brief.get("locations") or []),
    ]
    return " ".join(p for p in parts if p).strip() or chapter.title


def build_query_texts(
    chapter: Chapter, brief: dict[str, Any] | None = None
) -> list[str]:
    brief = brief or chapter.brief or {}
    goal = str(brief.get("goal") or "")
    conflict = str(brief.get("conflict") or "")
    must_events = [str(item) for item in (brief.get("must_events") or []) if item]
    characters = [str(item) for item in (brief.get("characters") or []) if item]
    locations = [str(item) for item in (brief.get("locations") or []) if item]
    forbidden = [str(item) for item in (brief.get("forbidden_events") or []) if item]
    hook = str(brief.get("hook") or "")
    queries = [
        " ".join(item for item in [chapter.title, goal, conflict] if item),
        " ".join([chapter.title, *must_events]),
        " ".join([chapter.title, *characters, *locations]),
        " ".join([chapter.title, hook, *forbidden]),
    ]
    return list(dict.fromkeys(item.strip() for item in queries if item.strip()))


def _entity_match(text: str, names: list[str]) -> float:
    if not names:
        return 0.0
    hits = sum(1 for name in names if name and name in text)
    return min(1.0, hits / max(1, min(3, len(names))))


def _lexical_overlap(query: str, content: str) -> float:
    q_tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{3,}", query.lower()))
    if not q_tokens:
        return 0.0
    c_tokens = set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{3,}", content.lower()))
    if not c_tokens:
        return 0.0
    return len(q_tokens & c_tokens) / len(q_tokens)


def _diversify(hits: list[RetrievalHit], limit: int) -> list[RetrievalHit]:
    selected: list[RetrievalHit] = []
    remaining = list(hits)
    chapter_counts: dict[str, int] = {}
    while remaining and len(selected) < limit:
        best_index = 0
        best_score = float("-inf")
        for index, hit in enumerate(remaining):
            overlap = max(
                (_lexical_overlap(hit.chunk.content, item.chunk.content) for item in selected),
                default=0.0,
            )
            same_chapter = chapter_counts.get(hit.chunk.chapter_id, 0)
            adjusted = hit.score - overlap * 0.16 - same_chapter * 0.035
            if adjusted > best_score:
                best_index = index
                best_score = adjusted
        chosen = remaining.pop(best_index)
        selected.append(replace(chosen, score=max(0.0, best_score)))
        chapter_counts[chosen.chunk.chapter_id] = chapter_counts.get(chosen.chunk.chapter_id, 0) + 1
    return selected
