from __future__ import annotations

import re
import time
import json
import hashlib
import inspect
from datetime import datetime, timezone
from typing import Any, Callable

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agents import (
    AgentScopeAuditor,
    AgentScopeWriter,
    extract_memory_delta,
    model_config_for_role,
    plan_scene_beats,
    run_continuity_skill,
)
from .agents.style import AgentScopeStyleAgent
from .agents.auditor import attach_evidence_metadata
from .craft import (
    CKSKILL_RULESET_VERSION,
    build_writing_contract,
    deterministic_craft_issues,
)
from .domain import AuditPolicy, ChapterState, JobState, VersionConflictError
from .memory.context_budget import (
    ContextBudget,
    ContextBudgeter,
    estimate_tokens,
    truncate_text,
)
from .memory.embeddings import resolve_embedding
from .memory.impact import compute_impact
from .memory.qdrant_store import QdrantVectorStore, delete_chunk_vectors
from .memory.retrieval import HybridRetriever, build_query_texts
from .memory.summaries import SummaryService, summary_payload
from .models import (
    AuditConfig,
    Chapter,
    ChapterAudit,
    ChapterVersion,
    GenerationJob,
    MemoryChunk,
    ModelConfig,
    NarrativeSummary,
    Novel,
    NovelRule,
    OutlineNode,
    PlotThread,
    StoryEntity,
    StoryEvent,
    new_id,
)
from .ports import WritingModel
from .repositories import SqlAlchemyRepository
from .security import decrypt_secret


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class OpenAICompatibleWritingModel:
    def __init__(
        self,
        config: ModelConfig,
        session: Session | None = None,
        *,
        novel_id: str = "",
        chapter_id: str | None = None,
    ):
        self.config = config
        self.name = config.name
        self.session = session
        self.novel_id = novel_id
        self.chapter_id = chapter_id

    def generate(
        self,
        *,
        title: str,
        brief: dict,
        existing_content: str,
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        from .observability import track_agent_call

        if not self.config.base_url:
            raise ValueError(f"模型 {self.config.name} 未配置 Base URL")
        context = brief.get("_context", {})
        task = {key: value for key, value in brief.items() if key != "_context"}
        prompt = {
            "chapterTitle": title,
            "chapterTask": task,
            "authoritativeContext": context,
            "existingContent": existing_content,
        }
        with track_agent_call(
            self.session,
            novel_id=self.novel_id,
            chapter_id=self.chapter_id,
            agent_name="Writer",
            model_name=self.name,
            operation="generate",
            input_summary=title,
        ) as meta:
            response = httpx.post(
                f"{self.config.base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {decrypt_secret(self.config.encrypted_api_key)}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.config.model_id,
                    "temperature": self.config.temperature / 100,
                    "max_tokens": self.config.max_output_tokens,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "你是长篇小说写作 Agent。权威事实和禁止规则不可违背；"
                                "只输出章节正文，不解释写作过程。"
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(prompt, ensure_ascii=False),
                        },
                    ],
                },
                timeout=120,
            )
            response.raise_for_status()
            payload = response.json()
            usage = payload.get("usage") or {}
            meta["input_tokens"] = usage.get("prompt_tokens") or usage.get("input_tokens")
            meta["output_tokens"] = usage.get("completion_tokens") or usage.get("output_tokens")
            content = payload.get("choices", [{}])[0].get("message", {}).get("content")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("模型没有返回可用正文")
            text = content.strip()
            if on_delta is not None:
                on_delta(text)
            meta["output_summary"] = text[:200]
            return text


class WritingPolicyService:
    """Resolve a versioned, structured CKSKILL contract for one chapter."""

    def __init__(self, session: Session):
        self.session = session

    def contract(
        self,
        chapter: Chapter,
        *,
        overrides: dict[str, Any] | None = None,
        dynamic_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        novel = self.session.get(Novel, chapter.novel_id)
        brief = dict(chapter.brief or {})
        values = dict(overrides or {})
        forbidden = [
            *list(brief.get("forbidden_events") or []),
            *list(values.pop("must_not_include", []) or []),
        ]
        for key, value in values.items():
            if value not in (None, "", [], {}):
                brief[key] = value
        if forbidden:
            brief["forbidden_events"] = list(dict.fromkeys(str(item) for item in forbidden if item))
        resolved_context = dict(dynamic_context or {})
        previous = self.session.scalar(
            select(Chapter)
            .where(
                Chapter.novel_id == chapter.novel_id,
                Chapter.chapter_index < chapter.chapter_index,
            )
            .order_by(Chapter.chapter_index.desc())
        )
        if previous is not None:
            previous_brief = dict(previous.brief or {})
            previous_directive = previous_brief.get("chapter_directive")
            previous_source = {
                **previous_brief,
                **(previous_directive if isinstance(previous_directive, dict) else {}),
            }
            resolved_context.setdefault(
                "previousChapterContract",
                {
                    "chapterIndex": previous.chapter_index,
                    "title": previous.title,
                    "cen": str(previous_source.get("cen") or previous_source.get("CEN") or "").strip(),
                    "chapterEndOpenQuestion": str(
                        previous_source.get("chapter_end_open_question")
                        or previous_source.get("open_question")
                        or previous_source.get("hook")
                        or ""
                    ).strip(),
                },
            )
        return build_writing_contract(
            profile=novel.writing_profile if novel else {},
            genre=novel.genre if novel else "",
            chapter_index=chapter.chapter_index,
            chapter_title=chapter.title,
            brief=brief,
            dynamic_context=resolved_context,
        )


class ContextAssembler:
    MAX_ENTITIES = 15
    MAX_THREADS = 8

    def __init__(self, session: Session):
        self.session = session

    def build(
        self,
        chapter: Chapter,
        brief: dict[str, Any] | None = None,
        existing_content: str = "",
    ) -> tuple[dict[str, Any], list[dict[str, str]]]:
        brief = brief or chapter.brief or {}
        novel = self.session.get(Novel, chapter.novel_id)
        rules = self.session.scalars(
            select(NovelRule).where(NovelRule.novel_id == chapter.novel_id)
        ).all()
        entities = self.session.scalars(
            select(StoryEntity).where(StoryEntity.novel_id == chapter.novel_id)
        ).all()
        threads = self.session.scalars(
            select(PlotThread).where(
                PlotThread.novel_id == chapter.novel_id,
                PlotThread.status.not_in(["PAID_OFF", "ABANDONED"]),
            )
        ).all()
        outline = self._outline_context(chapter)
        summary_names = {
            str(name)
            for node in (outline.get("hierarchy") or [])
            for name in ((node.get("narrativeSummary") or {}).get("entityNames") or [])
            if str(name).strip()
        }
        seed_text = self._search_text(brief, outline)
        seed_entity_names = [item.name for item in entities if item.name in seed_text]
        seed_plot_names = [item.name for item in threads if item.name in seed_text]

        queries = build_query_texts(chapter, brief=brief)
        hits = HybridRetriever(self.session).search_many(
            novel_id=chapter.novel_id,
            chapter=chapter,
            query_texts=queries,
            entity_names=seed_entity_names,
            plot_names=seed_plot_names,
            limit=8,
        )
        rag_text = "\n".join(hit.chunk.content for hit in hits)
        selected_entities = self._select_entities(
            entities,
            brief=brief,
            seed_text=seed_text,
            rag_text=rag_text,
            summary_names=summary_names,
        )
        selected_names = {item.name for item in selected_entities}
        selected_threads = self._select_threads(
            threads,
            seed_text=seed_text,
            rag_text=rag_text,
            entity_names=selected_names,
        )

        recent_chapters = self.session.scalars(
            select(Chapter)
            .where(
                Chapter.novel_id == chapter.novel_id,
                Chapter.chapter_index < chapter.chapter_index,
                Chapter.confirmed_version_id.is_not(None),
            )
            .order_by(Chapter.chapter_index.desc())
            .limit(3)
        ).all()
        recent: list[dict[str, Any]] = []
        sources: list[dict[str, str]] = []
        ordered_recent = list(reversed(recent_chapters))
        for index, item in enumerate(ordered_recent):
            version = self.session.get(ChapterVersion, item.confirmed_version_id)
            if version is None:
                continue
            summary = SummaryService(self.session).get(
                chapter.novel_id, "chapter", item.id
            )
            payload = {
                "chapterIndex": item.chapter_index,
                "title": item.title,
                "summary": (
                    summary_payload(summary)
                    if summary is not None
                    else {
                        "scopeType": "chapter",
                        "scopeId": item.id,
                        "summary": self._fallback_chapter_summary(version.content),
                        "canonicalFacts": [],
                        "openLoops": [],
                        "entityNames": [],
                        "sourceChapterIds": [item.id],
                    }
                ),
            }
            if index == len(ordered_recent) - 1:
                payload["continuationTail"] = version.content[-1200:]
            recent.append(payload)
            sources.append(
                {
                    "type": "chapterSummary",
                    "id": item.id,
                    "label": f"第 {item.chapter_index} 章摘要 · {item.title}",
                }
            )
        for node in outline["hierarchy"]:
            sources.append(
                {
                    "type": "outline",
                    "id": node["id"],
                    "label": f"{node['kind']} · {node['title']}",
                }
            )
        memory_texts: list[str] = []
        for hit in hits:
            memory_texts.append(hit.chunk.content)
            sources.append(hit.as_source())

        relevant_rules = self._select_rules(
            rules,
            seed_text=seed_text,
            rag_text=rag_text,
            entity_names=selected_names,
        )
        character_states = [
            item
            for item in self._character_states_for_context(chapter)
            if item.get("name") in selected_names
        ]
        location_states = [
            item
            for item in self._location_states_for_context(chapter)
            if item.get("name") in selected_names
        ]
        context = {
                "novel": {
                    "title": novel.title if novel else "",
                    "genre": novel.genre if novel else "",
                    "style": novel.style if novel else "",
                    "narrativePov": novel.narrative_pov if novel else "",
                    "tense": novel.tense if novel else "",
                },
                "rules": [
                    {"rule": item.rule, "importance": item.importance, "locked": item.locked}
                    for item in relevant_rules
                ],
                "entities": [
                    {
                        "type": item.entity_type,
                        "name": item.name,
                        "summary": item.summary,
                        "facts": item.data,
                    }
                    for item in selected_entities
                ],
                "recentConfirmedChapters": recent,
                "outline": outline,
                "plotThreads": [
                    {
                        "name": item.name,
                        "kind": item.kind,
                        "status": item.status,
                        "latest": item.latest,
                    }
                    for item in selected_threads
                ],
                "memory": memory_texts,
                "retrievalQuery": queries[0] if queries else chapter.title,
                "retrievalQueries": queries,
                "characterStates": character_states,
                "locationStates": location_states,
        }
        model_config = model_config_for_role(self.session, chapter.novel_id, "写作")
        task_payload = {key: value for key, value in brief.items() if not key.startswith("_")}
        task_tokens = estimate_tokens(task_payload) + estimate_tokens(existing_content) + 2048
        budget = ContextBudget.create(
            context_window=model_config.context_size if model_config else 32768,
            max_output_tokens=model_config.max_output_tokens if model_config else 4096,
            task_tokens=task_tokens,
        )
        fitted, report = ContextBudgeter(budget).fit(context)
        fitted["budget"] = report
        fitted["writingContract"] = WritingPolicyService(self.session).contract(
            chapter,
            overrides=task_payload,
            dynamic_context=fitted,
        )
        sources.append(
            {
                "type": "policy",
                "id": f"ckskill:{CKSKILL_RULESET_VERSION}",
                "label": f"CKSKILL 写作规则 {CKSKILL_RULESET_VERSION}",
            }
        )
        return fitted, sources

    def _outline_context(self, chapter: Chapter) -> dict[str, Any]:
        hierarchy: list[dict[str, Any]] = []
        node = (
            self.session.get(OutlineNode, chapter.outline_node_id)
            if chapter.outline_node_id
            else None
        )
        seen: set[str] = set()
        while node is not None and node.id not in seen:
            seen.add(node.id)
            hierarchy.append(
                {
                    "id": node.id,
                    "kind": node.kind,
                    "title": node.title,
                    **self._outline_node_payload(chapter, node),
                }
            )
            node = self.session.get(OutlineNode, node.parent_id) if node.parent_id else None
        hierarchy.reverse()
        return {"hierarchy": hierarchy}

    def _outline_node_payload(
        self, chapter: Chapter, node: OutlineNode
    ) -> dict[str, Any]:
        if node.kind == "chapter" and node.id == chapter.outline_node_id:
            return {}
        details = node.details or {}
        allowed = (
            "summary",
            "goal",
            "conflict",
            "theme",
            "core_conflict",
            "main_goal",
            "opening_state",
            "turning_points",
            "closing_state",
            "must_events",
            "forbidden_events",
        )
        plan = {
            key: self._truncate_value(details[key], 900)
            for key in allowed
            if key in details and details[key] not in (None, "", [], {})
        }
        payload: dict[str, Any] = {}
        if plan:
            payload["plan"] = plan
        summary = SummaryService(self.session).get(chapter.novel_id, node.kind, node.id)
        if summary is not None:
            payload["narrativeSummary"] = summary_payload(summary)
        return payload

    @staticmethod
    def manifest(
        context: dict[str, Any], sources: list[dict[str, str]]
    ) -> dict[str, Any]:
        return {
            "outlineNodes": len((context.get("outline") or {}).get("hierarchy") or []),
            "ragChunks": len(context.get("memory") or []),
            "recentChapters": len(context.get("recentConfirmedChapters") or []),
            "entities": len(context.get("entities") or []),
            "plotThreads": len(context.get("plotThreads") or []),
            "characterStates": len(context.get("characterStates") or []),
            "locationStates": len(context.get("locationStates") or []),
            "retrievalQuery": context.get("retrievalQuery") or "",
            "retrievalQueries": context.get("retrievalQueries") or [],
            "estimatedTokens": (context.get("budget") or {}).get("estimatedTokens", 0),
            "authoritativeLimit": (context.get("budget") or {}).get("authoritativeLimit", 0),
            "droppedItems": (context.get("budget") or {}).get("droppedItems", {}),
            "truncated": bool((context.get("budget") or {}).get("truncated")),
            "ruleset": (context.get("writingContract") or {}).get("ruleset"),
            "prewriteGate": (context.get("writingContract") or {}).get("gate", {}).get("status"),
        }

    @staticmethod
    def _search_text(*values: Any) -> str:
        return " ".join(
            json.dumps(value, ensure_ascii=False, default=str) for value in values
        )

    @staticmethod
    def _fallback_chapter_summary(content: str) -> str:
        body = content.strip()
        if len(body) <= 720:
            return body
        return body[:360].rstrip() + "…" + body[-360:].lstrip()

    @staticmethod
    def _truncate_value(value: Any, token_limit: int) -> Any:
        if isinstance(value, str):
            return truncate_text(value, token_limit)
        if isinstance(value, list):
            kept: list[Any] = []
            for item in value:
                candidate = [*kept, item]
                if estimate_tokens(candidate) > token_limit:
                    break
                kept.append(item)
            return kept
        if isinstance(value, dict):
            compact: dict[str, Any] = {}
            for key, item in value.items():
                candidate = {**compact, key: item}
                if estimate_tokens(candidate) > token_limit:
                    break
                compact[key] = item
            return compact
        return value

    def _select_entities(
        self,
        entities: list[StoryEntity],
        *,
        brief: dict[str, Any],
        seed_text: str,
        rag_text: str,
        summary_names: set[str],
    ) -> list[StoryEntity]:
        explicit = {
            str(name)
            for key in ("characters", "locations")
            for name in (brief.get(key) or [])
            if str(name).strip()
        }

        def score(item: StoryEntity) -> tuple[int, str]:
            value = 0
            value += 100 if item.name in explicit else 0
            value += 60 if item.name in seed_text else 0
            value += 45 if item.name in rag_text else 0
            value += 35 if item.name in summary_names else 0
            value += 20 if item.locked_fields else 0
            return value, item.name

        ranked = sorted(entities, key=score, reverse=True)
        selected = [item for item in ranked if score(item)[0] > 0]
        if len(selected) < min(5, len(ranked)):
            selected.extend(item for item in ranked if item not in selected)
        return selected[: self.MAX_ENTITIES]

    def _select_threads(
        self,
        threads: list[PlotThread],
        *,
        seed_text: str,
        rag_text: str,
        entity_names: set[str],
    ) -> list[PlotThread]:
        corpus = seed_text + "\n" + rag_text
        importance = {"高": 30, "中": 10, "低": 0}

        def score(item: PlotThread) -> tuple[int, str]:
            value = 80 if item.name and item.name in corpus else 0
            value += 35 if any(name in (item.latest or "") for name in entity_names) else 0
            value += importance.get(item.importance, 0)
            value += 10 if item.status in {"READY", "DEVELOPING"} else 0
            return value, item.name

        return sorted(threads, key=score, reverse=True)[: self.MAX_THREADS]

    @staticmethod
    def _select_rules(
        rules: list[NovelRule],
        *,
        seed_text: str,
        rag_text: str,
        entity_names: set[str],
    ) -> list[NovelRule]:
        locked = [item for item in rules if item.locked]
        corpus = seed_text + "\n" + rag_text
        importance = {"高": 30, "中": 10, "低": 0}

        def score(item: NovelRule) -> tuple[int, str]:
            value = importance.get(item.importance, 0)
            value += 50 if any(name in item.rule for name in entity_names) else 0
            terms = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{3,}", item.rule)
            value += min(30, sum(3 for term in terms if term in corpus))
            return value, item.rule

        ordinary = sorted((item for item in rules if not item.locked), key=score, reverse=True)
        return [*locked, *ordinary[:12]]

    def _character_states_for_context(self, chapter: Chapter) -> list[dict[str, Any]]:
        from .services_state import StateService

        return StateService(self.session).latest_character_states(
            chapter.novel_id, before_index=chapter.chapter_index
        )

    def _location_states_for_context(self, chapter: Chapter) -> list[dict[str, Any]]:
        from .services_state import StateService

        return StateService(self.session).latest_location_states(
            chapter.novel_id, before_index=chapter.chapter_index
        )


class ChapterService:
    def __init__(self, session: Session):
        self.session = session
        self.repo = SqlAlchemyRepository(session)

    def _next_sequence(self, chapter_id: str) -> int:
        current = self.session.scalar(
            select(func.max(ChapterVersion.sequence)).where(
                ChapterVersion.chapter_id == chapter_id
            )
        )
        return (current or 0) + 1

    def create_version(
        self,
        chapter: Chapter,
        *,
        content: str,
        title: str | None,
        source: str,
        base_version_id: str | None,
        model_name: str | None = None,
        make_current: bool = True,
        locked_ranges: list[dict[str, Any]] | None = None,
    ) -> ChapterVersion:
        if make_current and chapter.current_version_id != base_version_id:
            raise VersionConflictError(
                "Chapter changed after this edit started; refresh before saving again."
            )
        resolved_title = title or chapter.title
        resolved_locked_ranges = locked_ranges or []
        if make_current and source == "user" and chapter.current_version_id:
            current = self.repo.get_version(chapter.current_version_id)
            if (
                current.content == content
                and current.title == resolved_title
                and (current.locked_ranges or []) == resolved_locked_ranges
            ):
                return current
        version = ChapterVersion(
            workspace_id=chapter.workspace_id,
            novel_id=chapter.novel_id,
            chapter_id=chapter.id,
            sequence=self._next_sequence(chapter.id),
            source=source,
            title=resolved_title,
            content=content,
            content_json={"type": "doc", "text": content},
            model_name=model_name,
            base_version_id=base_version_id,
            locked_ranges=resolved_locked_ranges,
        )
        self.session.add(version)
        self.session.flush()
        if make_current:
            chapter.current_version_id = version.id
            chapter.title = version.title
            chapter.state = ChapterState.DRAFT
        self.session.commit()
        return version

    def restore(
        self,
        chapter: Chapter,
        target: ChapterVersion,
        _current_content: str | None = None,
    ) -> ChapterVersion:
        if target.chapter_id != chapter.id:
            raise ValueError("Version does not belong to chapter")
        chapter.current_version_id = target.id
        chapter.title = target.title
        chapter.latest_score = target.audit_score
        chapter.state = (
            ChapterState.CONFIRMED
            if chapter.confirmed_version_id == target.id
            else ChapterState.REVIEW_REQUIRED
            if target.audit_score is not None
            else ChapterState.DRAFT
        )
        chapter.memory_status = (
            "INDEXED" if chapter.confirmed_version_id == target.id else "NOT_INDEXED"
        )
        self.session.commit()
        return target

    def accept_candidate(
        self,
        chapter: Chapter,
        candidate: ChapterVersion,
    ) -> ChapterVersion:
        if candidate.chapter_id != chapter.id:
            raise ValueError("Version does not belong to chapter")
        chapter.current_version_id = candidate.id
        chapter.title = candidate.title
        chapter.latest_score = candidate.audit_score
        chapter.state = (
            ChapterState.REVIEW_REQUIRED
            if candidate.audit_score is not None
            else ChapterState.DRAFT
        )
        chapter.memory_status = "NOT_INDEXED"
        self.session.commit()
        return candidate

    def delete_version(self, chapter: Chapter, version: ChapterVersion) -> None:
        if version.chapter_id != chapter.id:
            raise ValueError("Version does not belong to chapter")
        if chapter.current_version_id == version.id:
            raise VersionConflictError("The current version cannot be deleted")

        replacement_base_id = version.base_version_id
        dependent_versions = self.session.scalars(
            select(ChapterVersion).where(
                ChapterVersion.chapter_id == chapter.id,
                ChapterVersion.base_version_id == version.id,
            )
        ).all()
        for dependent in dependent_versions:
            dependent.base_version_id = replacement_base_id

        related_audits = self.session.scalars(
            select(ChapterAudit).where(ChapterAudit.version_id == version.id)
        ).all()
        related_memory = self.session.scalars(
            select(MemoryChunk).where(MemoryChunk.version_id == version.id)
        ).all()
        related_summaries = self.session.scalars(
            select(NarrativeSummary).where(NarrativeSummary.version_id == version.id)
        ).all()
        delete_chunk_vectors(self.session, related_memory)
        for item in [*related_audits, *related_memory, *related_summaries]:
            self.session.delete(item)
        if chapter.confirmed_version_id == version.id:
            chapter.confirmed_version_id = None
            chapter.memory_status = "NOT_INDEXED"
        self.session.delete(version)
        self.session.commit()


class MemoryService:
    CHUNK_SIZE = 1200
    CHUNK_OVERLAP = 160

    def __init__(self, session: Session):
        self.session = session

    def index_confirmed_version(
        self, chapter: Chapter, version: ChapterVersion, *, force_reembed: bool = False
    ) -> list[MemoryChunk]:
        existing = self.session.scalars(
            select(MemoryChunk).where(MemoryChunk.version_id == version.id)
        ).all()
        provider = resolve_embedding(self.session, chapter.novel_id)
        dimensions = provider.dimensions()
        vector_store = QdrantVectorStore(self.session, dimensions)

        if existing and not force_reembed:
            missing_ids = vector_store.missing_chunk_ids(item.id for item in existing)
            to_index = [
                item
                for item in existing
                if item.id in missing_ids
                or item.embedding_model_id != provider.model_id
                or item.embedding_version != provider.version
                or item.embedding_dimensions != dimensions
            ]
            if to_index:
                old_dimension_chunks = [
                    item
                    for item in to_index
                    if item.embedding_dimensions
                    and item.embedding_dimensions != dimensions
                ]
                delete_chunk_vectors(self.session, old_dimension_chunks)
                vectors = provider.embed_documents([item.content for item in to_index])
                vector_store.upsert(
                    to_index,
                    vectors,
                    model_id=provider.model_id,
                    model_version=provider.version,
                )
            for item in existing:
                meta = dict(item.metadata_json or {})
                meta.pop("embedding", None)
                meta["embeddingModelId"] = provider.model_id
                meta["embeddingVersion"] = provider.version
                item.metadata_json = meta
                item.embedding_model_id = provider.model_id
                item.embedding_version = provider.version
                item.embedding_dimensions = dimensions
                item.index_status = "INDEXED"
            chapter.memory_status = (
                "INDEXED"
                if existing and all(item.index_status == "INDEXED" for item in existing)
                else "PENDING"
            )
            self.session.commit()
            return list(existing)

        if existing and force_reembed:
            delete_chunk_vectors(self.session, existing)
            for item in existing:
                self.session.delete(item)
            self.session.flush()

        text = version.content.strip()
        raw_chunks: list[str] = []
        start = 0
        while start < len(text):
            end = min(len(text), start + self.CHUNK_SIZE)
            if end < len(text):
                boundary = max(text.rfind("\n", start, end), text.rfind("。", start, end))
                if boundary > start + self.CHUNK_SIZE // 2:
                    end = boundary + 1
            content = text[start:end].strip()
            if content:
                raw_chunks.append(content)
            if end >= len(text):
                break
            start = max(start + 1, end - self.CHUNK_OVERLAP)

        vectors = provider.embed_documents(raw_chunks) if raw_chunks else []
        chunks: list[MemoryChunk] = []
        for index, content in enumerate(raw_chunks):
            vector = vectors[index] if index < len(vectors) else []
            chunks.append(
                MemoryChunk(
                    workspace_id=chapter.workspace_id,
                    novel_id=chapter.novel_id,
                    chapter_id=chapter.id,
                    version_id=version.id,
                    chunk_index=index,
                    content=content,
                    summary=content[:160],
                    metadata_json={
                        "chapterIndex": chapter.chapter_index,
                        "chapterTitle": chapter.title,
                        "confirmed": True,
                        "importance": 0.6,
                        "embeddingModelId": provider.model_id,
                        "embeddingVersion": provider.version,
                    },
                    embedding_model_id=provider.model_id,
                    embedding_version=provider.version,
                    embedding_dimensions=dimensions,
                    index_status="PENDING",
                )
            )

        self.session.add_all(chunks)
        chapter.memory_status = "PENDING" if chunks else "INDEXED"
        self.session.commit()
        if chunks:
            try:
                vector_store.upsert(
                    chunks,
                    vectors,
                    model_id=provider.model_id,
                    model_version=provider.version,
                )
            except Exception:
                chapter.memory_status = "PENDING"
                self.session.commit()
                raise
            for chunk in chunks:
                chunk.index_status = "INDEXED"
            chapter.memory_status = "INDEXED"
            self.session.commit()
        return chunks

    def reindex_novel(self, novel_id: str) -> dict[str, Any]:
        chapters = self.session.scalars(
            select(Chapter)
            .where(
                Chapter.novel_id == novel_id,
                Chapter.confirmed_version_id.is_not(None),
            )
            .order_by(Chapter.chapter_index)
        ).all()
        total_chunks = 0
        for chapter in chapters:
            version = self.session.get(ChapterVersion, chapter.confirmed_version_id)
            if version is None:
                continue
            chunks = self.index_confirmed_version(chapter, version, force_reembed=True)
            total_chunks += len(chunks)
        summaries = SummaryService(self.session).rebuild_novel(novel_id)
        provider = resolve_embedding(self.session, novel_id)
        return {
            "novelId": novel_id,
            "confirmedChapters": len(chapters),
            "chunks": total_chunks,
            "embeddingModelId": provider.model_id,
            "embeddingVersion": provider.version,
            "summaries": summaries,
            "status": "INDEXED" if total_chunks or not chapters else "EMPTY",
        }

    def memory_status(self, novel_id: str) -> dict[str, Any]:
        chapters = self.session.scalars(
            select(Chapter).where(Chapter.novel_id == novel_id)
        ).all()
        confirmed = [c for c in chapters if c.confirmed_version_id]
        chunks = self.session.scalars(
            select(MemoryChunk).where(MemoryChunk.novel_id == novel_id)
        ).all()
        indexed = [c for c in chunks if c.index_status == "INDEXED"]
        pending = [c for c in chapters if c.memory_status == "PENDING"]
        outdated = [c for c in chapters if c.state == ChapterState.OUTDATED or c.needs_check]
        from .memory.embeddings import is_neural_embedding

        provider = resolve_embedding(self.session, novel_id)
        vector_store = QdrantVectorStore(self.session, provider.dimensions())
        vector_count = vector_store.count(
            workspace_id=chapters[0].workspace_id if chapters else "local",
            novel_id=novel_id,
            model_id=provider.model_id,
            model_version=provider.version,
        )
        neural = is_neural_embedding(provider)
        models = {
            c.embedding_model_id
            for c in indexed
            if c.embedding_model_id
        }
        needs_rebuild = bool(models) and (
            provider.model_id not in models or len(models) > 1
        )
        return {
            "novelId": novel_id,
            "confirmedChapters": len(confirmed),
            "chunkCount": len(chunks),
            "indexedChunkCount": len(indexed),
            "embeddedChunkCount": vector_count,
            "pendingChapters": len(pending),
            "needsCheckChapters": len(outdated),
            "embeddingModelId": provider.model_id,
            "embeddingVersion": provider.version,
            "embeddingMode": "neural" if neural else "hash_fallback",
            "hasNeuralEmbedding": neural,
            "needsRebuild": needs_rebuild,
            "vectorStore": vector_store.status(),
            "status": "INDEXED"
            if indexed and vector_count >= len(indexed)
            else ("PENDING" if chunks else "EMPTY"),
        }

    def commit_confirmed_memory(
        self,
        chapter: Chapter,
        version: ChapterVersion,
        *,
        previous_confirmed_version_id: str | None = None,
    ) -> dict[str, Any]:
        """Two-phase memory: extract candidates, validate, then write facts + chunks."""
        previous_confirmed = None
        # Re-confirm path: caller passes the prior confirmed version id.
        if previous_confirmed_version_id and previous_confirmed_version_id != version.id:
            previous_confirmed = self.session.get(
                ChapterVersion, previous_confirmed_version_id
            )

        old_delta: dict[str, Any] | None = None
        if previous_confirmed is not None:
            entities = self.session.scalars(
                select(StoryEntity).where(StoryEntity.novel_id == chapter.novel_id)
            ).all()
            threads = self.session.scalars(
                select(PlotThread).where(PlotThread.novel_id == chapter.novel_id)
            ).all()
            old_delta = extract_memory_delta(
                self.session,
                chapter=chapter,
                content=previous_confirmed.content,
                existing_entities=[
                    {
                        "name": item.name,
                        "type": item.entity_type,
                        "summary": item.summary,
                        "facts": item.data,
                    }
                    for item in entities
                ],
                existing_threads=[
                    {
                        "name": item.name,
                        "kind": item.kind,
                        "status": item.status,
                        "latest": item.latest,
                    }
                    for item in threads
                ],
            )

        chunks = self.index_confirmed_version(chapter, version, force_reembed=bool(previous_confirmed))

        entities = self.session.scalars(
            select(StoryEntity).where(StoryEntity.novel_id == chapter.novel_id)
        ).all()
        threads = self.session.scalars(
            select(PlotThread).where(PlotThread.novel_id == chapter.novel_id)
        ).all()
        entity_payload = [
            {
                "name": item.name,
                "type": item.entity_type,
                "summary": item.summary,
                "facts": item.data,
            }
            for item in entities
        ]
        thread_payload = [
            {
                "name": item.name,
                "kind": item.kind,
                "status": item.status,
                "latest": item.latest,
            }
            for item in threads
        ]

        delta = extract_memory_delta(
            self.session,
            chapter=chapter,
            content=version.content,
            existing_entities=entity_payload,
            existing_threads=thread_payload,
        )
        committed = self._apply_memory_delta(chapter, delta)
        summaries = SummaryService(self.session).update_from_confirmation(
            chapter, version, delta
        )

        impact = None
        if previous_confirmed is not None:
            impact = compute_impact(
                self.session,
                chapter=chapter,
                old_delta=old_delta,
                new_delta=delta,
                force=True,
            )

        return {
            "chunks": len(chunks),
            "delta": delta,
            "committed": committed,
            "summaries": summaries,
            "impact": impact,
        }

    def _apply_memory_delta(
        self, chapter: Chapter, delta: dict[str, Any]
    ) -> dict[str, Any]:
        entities = {
            item.name: item
            for item in self.session.scalars(
                select(StoryEntity).where(StoryEntity.novel_id == chapter.novel_id)
            ).all()
        }
        threads = {
            item.name: item
            for item in self.session.scalars(
                select(PlotThread).where(PlotThread.novel_id == chapter.novel_id)
            ).all()
        }
        max_seq = self.session.scalar(
            select(func.max(StoryEvent.sequence)).where(
                StoryEvent.novel_id == chapter.novel_id
            )
        ) or 0
        existing_events = self.session.scalars(
            select(StoryEvent).where(
                StoryEvent.chapter_id == chapter.id,
                StoryEvent.source_outline_node_id.is_(None),
            )
        ).all()

        def event_key(
            story_time: str,
            subjects: list[str],
            action: str,
            location: str,
            consequences: str,
        ) -> tuple[str, tuple[str, ...], str, str, str]:
            return (
                story_time,
                tuple(sorted(subjects)),
                action,
                location,
                consequences,
            )

        existing_event_keys = {
            event_key(
                item.story_time,
                [str(subject) for subject in (item.subjects or [])],
                item.action,
                item.location,
                item.consequences,
            )
            for item in existing_events
        }

        resolved_events: list[tuple[str, list[str], str, str, str]] = []
        resolved_event_keys: set[tuple[str, tuple[str, ...], str, str, str]] = set()
        for item in delta.get("events") or []:
            action = str(item.get("action") or "").strip()
            if not action:
                continue
            subjects = [str(s) for s in (item.get("subjects") or []) if s]
            # Prefer known entities when subjects empty.
            if not subjects:
                subjects = [
                    name for name in entities if name and name in (chapter.title + action)
                ][:3]
            story_time = str(item.get("story_time") or f"第 {chapter.chapter_index} 章")
            location = str(item.get("location") or "")
            consequences = str(item.get("consequences") or "")
            key = event_key(story_time, subjects, action, location, consequences)
            if key in resolved_event_keys:
                continue
            resolved_event_keys.add(key)
            resolved_events.append(
                (story_time, subjects, action, location, consequences)
            )

        events_written = 0
        if resolved_event_keys != existing_event_keys:
            for existing in existing_events:
                self.session.delete(existing)
            for story_time, subjects, action, location, consequences in resolved_events:
                max_seq += 1
                self.session.add(
                    StoryEvent(
                        workspace_id=chapter.workspace_id,
                        novel_id=chapter.novel_id,
                        chapter_id=chapter.id,
                        story_time=story_time,
                        sequence=max_seq,
                        subjects=subjects,
                        action=action,
                        location=location,
                        consequences=consequences,
                    )
                )
                events_written += 1

        entities_updated = 0
        for item in delta.get("entity_updates") or []:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            entity = entities.get(name)
            facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
            summary = str(item.get("summary") or "")
            if entity is None:
                entity = StoryEntity(
                    workspace_id=chapter.workspace_id,
                    novel_id=chapter.novel_id,
                    entity_type=str(item.get("entity_type") or "character"),
                    name=name,
                    summary=summary,
                    data=facts,
                )
                self.session.add(entity)
                entities[name] = entity
                entities_updated += 1
                continue
            locked = set(entity.locked_fields or [])
            if summary and "summary" not in locked:
                entity.summary = summary
            if facts:
                merged = dict(entity.data or {})
                for key, value in facts.items():
                    if key in locked:
                        continue
                    merged[str(key)] = value
                entity.data = merged
            entities_updated += 1

        threads_updated = 0
        for item in delta.get("plot_threads") or []:
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            thread = threads.get(name)
            status = str(item.get("status") or "DEVELOPING")
            latest = str(item.get("latest") or "")
            if thread is None:
                thread = PlotThread(
                    workspace_id=chapter.workspace_id,
                    novel_id=chapter.novel_id,
                    name=name,
                    kind=str(item.get("kind") or "mystery"),
                    status=status,
                    planted=f"第 {chapter.chapter_index} 章",
                    latest=latest,
                )
                self.session.add(thread)
                threads[name] = thread
            else:
                thread.status = status
                if latest:
                    thread.latest = latest
            threads_updated += 1

        for name in delta.get("resolved_threads") or []:
            thread = threads.get(str(name))
            if thread is not None:
                thread.status = "PAID_OFF"
                thread.latest = thread.latest or f"第 {chapter.chapter_index} 章回收"
                threads_updated += 1

        # State extraction needs to see entities created above. Flush keeps the
        # whole memory delta in one transaction so a state failure rolls it back.
        self.session.flush()

        from .services_state import StateService

        state_counts = StateService(self.session).apply_from_memory_delta(chapter, delta)
        return {
            "events": events_written,
            "entities": entities_updated,
            "plotThreads": threads_updated,
            **state_counts,
        }


class AuditService:
    DEFAULT_DIMENSIONS = [
        {"name": "连续性", "max": 18},
        {"name": "人物一致性", "max": 12},
        {"name": "大纲完成度", "max": 15},
        {"name": "时间线", "max": 10},
        {"name": "剧情推进", "max": 10},
        {"name": "冲突张力", "max": 10},
        {"name": "亮点与转折", "max": 10},
        {"name": "文笔质量", "max": 8},
        {"name": "AI 痕迹", "max": 7},
    ]

    def __init__(self, session: Session):
        self.session = session

    def audit(
        self,
        chapter: Chapter,
        version: ChapterVersion,
        *,
        update_chapter: bool = True,
        protected_texts: list[str] | None = None,
    ) -> ChapterAudit:
        config = self.session.scalar(
            select(AuditConfig).where(AuditConfig.novel_id == chapter.novel_id)
        )
        dimensions = (config.dimensions if config else None) or self.DEFAULT_DIMENSIONS
        protected = list(protected_texts or [])
        hard_issues = self._hard_rule_issues(chapter, version, protected)
        craft_issues = deterministic_craft_issues(version.content, chapter.brief or {})

        llm_result: dict[str, Any] | None = None
        auditor_config = model_config_for_role(self.session, chapter.novel_id, "审计")
        if auditor_config is None:
            auditor_config = model_config_for_role(self.session, chapter.novel_id, "连续性")
        if auditor_config is not None:
            try:
                context, _ = ContextAssembler(self.session).build(
                    chapter,
                    brief=chapter.brief or {},
                    existing_content=version.content,
                )
                llm_result = AgentScopeAuditor(auditor_config).audit(
                    title=chapter.title,
                    content=version.content,
                    brief=chapter.brief or {},
                    context=context,
                    dimensions=dimensions,
                    protected_texts=protected,
                    pass_score=config.pass_score if config else 85,
                    revise_score=config.revise_score if config else 70,
                )
            except Exception:
                llm_result = None

        if llm_result is None:
            llm_result = self._heuristic_audit(chapter, version, dimensions, protected)

        issues = self._merge_issues(
            hard_issues,
            [*craft_issues, *(llm_result.get("issues") or [])],
        )
        issues = [attach_evidence_metadata(item, version.content) for item in issues]
        fatal = [item for item in issues if item["severity"] == "fatal"]
        policy = AuditPolicy(
            pass_score=config.pass_score if config else 85,
            revise_score=config.revise_score if config else 70,
            max_rewrite_attempts=min(1, config.max_rewrite_attempts) if config else 1,
            fatal_issue_force_rewrite=(
                config.fatal_issue_force_rewrite if config else True
            ),
        )
        total = int(llm_result.get("total_score") or 0)
        deterministic_fatal = [
            item for item in [*hard_issues, *craft_issues] if item.get("severity") == "fatal"
        ]
        if deterministic_fatal:
            # Hard rule failures always pull score down and force decision via policy.
            total = min(total, max(0, 100 - 30 * len(deterministic_fatal)))
        scores = llm_result.get("dimension_scores") or []
        if not scores:
            remaining_penalty = 100 - total
            for item in dimensions:
                maximum = int(item["max"])
                deduction = min(maximum, round(remaining_penalty * maximum / 100))
                scores.append(
                    {"name": item["name"], "score": maximum - deduction, "max": maximum}
                )

        decision = policy.decision(total, bool(fatal))
        rewrite = llm_result.get("rewrite_requirements") or {}
        audit = ChapterAudit(
            workspace_id=chapter.workspace_id,
            novel_id=chapter.novel_id,
            chapter_id=chapter.id,
            version_id=version.id,
            rubric_version=config.rubric_version if config else 1,
            total_score=total,
            decision=decision,
            dimension_scores=scores,
            fatal_issues=fatal,
            issues=issues,
            strengths=llm_result.get("strengths")
            or (["章节目标清晰", "结尾保留了后续推进空间"] if version.content.strip() else []),
            rewrite_requirements={
                "mustPreserve": rewrite.get("mustPreserve")
                or chapter.brief.get("must_preserve", [])
                or protected,
                "mustImprove": rewrite.get("mustImprove")
                or [item["suggestion"] for item in issues if item.get("suggestion")],
                "mustNotInclude": rewrite.get("mustNotInclude")
                or chapter.brief.get("forbidden_events", []),
                "lockedRanges": version.locked_ranges,
            },
        )
        self.session.add(audit)
        version.audit_score = total
        if update_chapter:
            chapter.latest_score = total
            chapter.state = ChapterState.REVIEW_REQUIRED
            chapter.needs_check = False
        self.session.commit()
        return audit

    def _hard_rule_issues(
        self,
        chapter: Chapter,
        version: ChapterVersion,
        protected_texts: list[str],
    ) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        content = version.content.strip()
        for forbidden in chapter.brief.get("forbidden_events", []):
            if forbidden and forbidden in content:
                issues.append(
                    {
                        "id": new_id(),
                        "severity": "fatal",
                        "type": "禁止事件",
                        "evidence": str(forbidden)[:120],
                        "conflictsWith": "本章大纲 forbidden_events 明确禁止",
                        "suggestion": "删除该事件，或先修改并确认章节大纲。",
                    }
                )
        for protected in protected_texts:
            if protected and protected not in content:
                issues.append(
                    {
                        "id": new_id(),
                        "severity": "fatal",
                        "type": "锁定内容",
                        "evidence": protected[:120],
                        "conflictsWith": "用户锁定内容不可被 AI 删除或改写",
                        "suggestion": "恢复完整锁定原文后重新审计。",
                    }
                )
        if "早就知道" in content:
            issues.append(
                {
                    "id": new_id(),
                    "severity": "fatal",
                    "type": "知识边界",
                    "evidence": "早就知道",
                    "conflictsWith": "人物知识必须来自已确认事件",
                    "suggestion": "改为推测，或补充人物获知信息的依据。",
                }
            )
        issues.extend(self._canonical_fact_issues(chapter, content))
        # Structured state continuity (death / destroyed locations).
        try:
            from .services_state import StateService

            for item in StateService(self.session).continuity_issues_from_states(
                novel_id=chapter.novel_id,
                chapter_index=chapter.chapter_index,
                content=content,
            ):
                issues.append(
                    {
                        "id": new_id(),
                        "severity": item.get("severity") or "major",
                        "type": item.get("type") or "连续性",
                        "evidence": str(item.get("evidence") or "")[:120],
                        "conflictsWith": str(item.get("reason") or "结构化状态冲突"),
                        "suggestion": "修正正文或更新权威状态后再审计。",
                    }
                )
        except Exception:
            pass
        return issues

    def _canonical_fact_issues(
        self, chapter: Chapter, content: str
    ) -> list[dict[str, Any]]:
        summaries = self.session.scalars(
            select(NarrativeSummary)
            .where(
                NarrativeSummary.novel_id == chapter.novel_id,
                NarrativeSummary.scope_type == "chapter",
                NarrativeSummary.end_chapter_index < chapter.chapter_index,
            )
            .order_by(NarrativeSummary.end_chapter_index.desc())
        ).all()
        issues: list[dict[str, Any]] = []
        seen: set[str] = set()
        for summary in summaries:
            for fact in summary.canonical_facts or []:
                raw = str(fact.get("fact") or "").strip()
                if not raw or raw in seen or fact.get("kind") != "entity_state":
                    continue
                seen.add(raw)
                match = re.match(r"^(.+?)\.(alive|body_status|bodyStatus|condition)=(.+)$", raw)
                if match is None:
                    continue
                name, key, raw_value = match.groups()
                value = raw_value.strip().lower()
                is_dead = key in {"alive", "body_status", "bodyStatus"} and value in {
                    "false",
                    "0",
                    "死亡",
                    "dead",
                }
                is_destroyed = key == "condition" and value in {"destroyed", "毁坏", "摧毁"}
                if name not in content:
                    continue
                explained = any(
                    marker in content
                    for marker in (
                        "复活",
                        "假死",
                        "误传",
                        "重建",
                        "修复",
                        "恢复",
                    )
                )
                if explained or not (is_dead or is_destroyed):
                    continue
                source_chapter = str(fact.get("sourceChapterId") or summary.chapter_id or "")
                source_version = str(fact.get("sourceVersionId") or summary.version_id or "")
                issues.append(
                    {
                        "id": new_id(),
                        "severity": "fatal",
                        "type": "权威事实冲突",
                        "evidence": name[:120],
                        "conflictsWith": (
                            f"已确认事实「{raw}」；来源章节 {source_chapter}，"
                            f"版本 {source_version}"
                        ),
                        "suggestion": "补充状态改变的明确过程，或修正正文以符合已确认事实。",
                    }
                )
        return issues

    def _heuristic_audit(
        self,
        chapter: Chapter,
        version: ChapterVersion,
        dimensions: list[dict[str, Any]],
        protected_texts: list[str],
    ) -> dict[str, Any]:
        issues: list[dict[str, Any]] = []
        content = version.content.strip()
        must_events = chapter.brief.get("must_events", [])
        missing_events = [event for event in must_events if event and event not in content]
        for event in missing_events:
            issues.append(
                {
                    "id": new_id(),
                    "severity": "major",
                    "type": "大纲完成度",
                    "evidence": f"正文未出现：{event}",
                    "conflictsWith": "章节必达事件",
                    "suggestion": f"在不破坏现有情节的前提下完成事件：{event}",
                }
            )
        if len(content) < max(300, chapter.target_words // 3):
            issues.append(
                {
                    "id": new_id(),
                    "severity": "minor",
                    "type": "剧情推进",
                    "evidence": f"当前正文仅 {len(content)} 字",
                    "conflictsWith": f"目标字数 {chapter.target_words}",
                    "suggestion": "补足场景行动、反应和后果。",
                }
            )
        repeated = re.search(r"(.{2,8})\1\1", content)
        if repeated:
            issues.append(
                {
                    "id": new_id(),
                    "severity": "minor",
                    "type": "AI 痕迹",
                    "evidence": repeated.group(0)[:60],
                    "conflictsWith": "避免模板化重复",
                    "suggestion": "打散重复句式。",
                }
            )
        hard = self._hard_rule_issues(chapter, version, protected_texts)
        issues = self._merge_issues(hard, issues)
        penalty = sum({"fatal": 30, "major": 12, "minor": 5}[i["severity"]] for i in issues)
        total = max(0, 100 - penalty)
        remaining_penalty = 100 - total
        scores = []
        for item in dimensions:
            maximum = int(item["max"])
            deduction = min(maximum, round(remaining_penalty * maximum / 100))
            scores.append({"name": item["name"], "score": maximum - deduction, "max": maximum})
        return {
            "total_score": total,
            "dimension_scores": scores,
            "issues": issues,
            "strengths": ["章节目标清晰", "结尾保留了后续推进空间"] if content else [],
            "rewrite_requirements": {
                "mustPreserve": chapter.brief.get("must_preserve", []) or protected_texts,
                "mustImprove": [item["suggestion"] for item in issues],
                "mustNotInclude": chapter.brief.get("forbidden_events", []),
            },
        }

    @staticmethod
    def _merge_issues(
        hard: list[dict[str, Any]], soft: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in [*hard, *soft]:
            key = (str(item.get("type") or ""), str(item.get("evidence") or "")[:80])
            if key in seen:
                continue
            seen.add(key)
            if "id" not in item:
                item = {**item, "id": new_id()}
            merged.append(item)
        return merged


class SelectionEditService:
    """Local selection rewrite; returns candidate text without overwriting chapter."""

    def __init__(self, session: Session):
        self.session = session

    def edit(
        self,
        chapter: Chapter,
        *,
        operation: str,
        start: int,
        end: int,
        selected_text: str,
        content: str,
        instruction: str = "",
    ) -> dict[str, Any]:
        from .observability import track_agent_call

        if end <= start or end > len(content):
            raise ValueError("invalid selection range")
        actual = content[start:end]
        if actual.strip() != selected_text.strip():
            raise ValueError("selected_text does not match content range")

        before = content[:start]
        after = content[end:]
        context, _ = ContextAssembler(self.session).build(
            chapter,
            brief={
                **(chapter.brief or {}),
                "selection_operation": operation,
                "selection_instruction": instruction,
            },
            existing_content=content,
        )

        config = model_config_for_role(self.session, chapter.novel_id, "润色")
        if config is None:
            config = model_config_for_role(self.session, chapter.novel_id, "写作")

        if config is None:
            raise ValueError("请先为本项目连接可用的云端写作模型。")
        model_name = config.name
        with track_agent_call(
            self.session,
            novel_id=chapter.novel_id,
            chapter_id=chapter.id,
            agent_name="Style",
            model_name=config.name,
            operation=operation,
            input_summary=selected_text[:120],
        ) as meta:
            try:
                candidate = AgentScopeStyleAgent(config).edit_selection(
                        operation=operation,
                        selected_text=selected_text,
                        before=before,
                        after=after,
                        instruction=instruction,
                        context=context,
                    )
            except Exception as exc:
                raise ValueError("云端模型未能完成局部修改，请检查连接后重试。") from exc
            meta["output_summary"] = candidate[:200]

        merged = before + candidate + after
        return {
            "operation": operation,
            "start": start,
            "end": end,
            "originalText": selected_text,
            "candidateText": candidate,
            "mergedContent": merged,
            "modelName": model_name,
            "instruction": instruction,
            "baseVersionId": chapter.current_version_id,
            # Does not write chapter versions — client must accept into editor.
            "applied": False,
        }


class GenerationService:
    STAGES = [
        "正在执行写前检查",
        "正在组装上下文",
        "正在设计场景节拍",
        "正在生成正文",
        "正在检查连续性",
        "正在审计",
    ]

    def __init__(self, session: Session, model: WritingModel | None = None):
        self.session = session
        self.repo = SqlAlchemyRepository(session)
        self.model = model

    def _model_for_novel(self, novel_id: str, chapter_id: str | None = None) -> WritingModel:
        config = model_config_for_role(self.session, novel_id, "写作")
        if config is not None:
            try:
                return AgentScopeWriter(
                    config,
                    session=self.session,
                    novel_id=novel_id,
                    chapter_id=chapter_id,
                )
            except Exception:
                return OpenAICompatibleWritingModel(
                    config, session=self.session, novel_id=novel_id, chapter_id=chapter_id
                )
        raise ValueError("请先为本项目连接可用的云端写作模型。")

    @staticmethod
    def _protected_texts(
        version: ChapterVersion | None, explicit: list[str] | None = None
    ) -> list[str]:
        protected = [item for item in explicit or [] if item]
        if not version:
            return protected
        for item in version.locked_ranges or []:
            start = int(item.get("start", -1))
            end = int(item.get("end", -1))
            if 0 <= start < end <= len(version.content):
                text = version.content[start:end]
                if text and text not in protected:
                    protected.append(text)
        return protected

    def create_job(
        self,
        chapter: Chapter,
        base_version_id: str | None,
        operation: str,
        options: dict[str, Any] | None = None,
    ) -> GenerationJob:
        options = options or {}
        options_hash = hashlib.sha256(
            json.dumps(options, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        key = f"{chapter.id}:{base_version_id or 'empty'}:{operation}:{options_hash}"
        existing = self.session.scalar(
            select(GenerationJob).where(GenerationJob.idempotency_key == key)
        )
        if existing and existing.state not in {JobState.FAILED, JobState.CANCELLED}:
            return existing
        if existing:
            key = f"{key}:{new_id()}"
        job = GenerationJob(
            workspace_id=chapter.workspace_id,
            novel_id=chapter.novel_id,
            chapter_id=chapter.id,
            job_type=operation,
            state=JobState.PENDING,
            base_version_id=base_version_id,
            idempotency_key=key,
            events=[
                {
                    "type": "queued",
                    "stage": "等待开始",
                    "request": options,
                    "at": utc_iso(),
                }
            ],
        )
        self.session.add(job)
        chapter.state = ChapterState.GENERATING
        self.session.commit()
        return job

    def _emit(self, job: GenerationJob, *, index: int, stage: str, **extra: Any) -> None:
        job.stage = stage
        event = {"type": "progress", "index": index, "stage": stage, "at": utc_iso(), **extra}
        job.events = [*job.events, event]
        self.session.commit()

    def _emit_content_delta(self, job: GenerationJob, delta: str, sequence: int) -> None:
        if not delta:
            return
        job.events = [
            *job.events,
            {
                "type": "content_delta",
                "delta": delta,
                "sequence": sequence,
                "at": utc_iso(),
            },
        ]
        self.session.commit()

    def _emit_content_reset(self, job: GenerationJob) -> None:
        job.events = [*job.events, {"type": "content_reset", "at": utc_iso()}]
        self.session.commit()

    def _generate_with_events(
        self,
        job: GenerationJob,
        model: WritingModel,
        *,
        title: str,
        brief: dict[str, Any],
        existing_content: str,
    ) -> str:
        pending: list[str] = []
        pending_length = 0
        last_flush = time.monotonic()
        sequence = 0

        def flush() -> None:
            nonlocal pending_length, last_flush, sequence
            if not pending:
                return
            sequence += 1
            self._emit_content_delta(job, "".join(pending), sequence)
            pending.clear()
            pending_length = 0
            last_flush = time.monotonic()

        def on_delta(delta: str) -> None:
            nonlocal pending_length
            if not delta:
                return
            pending.append(delta)
            pending_length += len(delta)
            if pending_length >= 48 or time.monotonic() - last_flush >= 0.08:
                flush()

        parameters = inspect.signature(model.generate).parameters
        if "on_delta" in parameters:
            content = model.generate(
                title=title,
                brief=brief,
                existing_content=existing_content,
                on_delta=on_delta,
            )
        else:
            content = model.generate(
                title=title,
                brief=brief,
                existing_content=existing_content,
            )
            on_delta(content)
        flush()
        return content

    def _cancelled(self, job: GenerationJob, chapter: Chapter) -> bool:
        self.session.refresh(job)
        if not job.cancel_requested:
            return False
        job.state = JobState.CANCELLED
        job.stage = "已取消"
        job.events = [*job.events, {"type": "cancelled", "stage": job.stage, "at": utc_iso()}]
        chapter.state = ChapterState.DRAFT if chapter.current_version_id else ChapterState.PLANNED
        self.session.commit()
        return True

    def run_job(self, job_id: str, auto_audit: bool = True) -> None:
        job = self.repo.get_job(job_id)
        chapter = self.repo.get_chapter(job.chapter_id or "")
        job.state = JobState.RUNNING
        self.session.commit()
        try:
            if job.job_type == "AUDIT_AND_REWRITE":
                self._run_audit_and_rewrite(job, chapter)
                return

            base = self.session.get(ChapterVersion, job.base_version_id) if job.base_version_id else None
            options = (job.events[0].get("request", {}) if job.events else {}) or {}
            protected_texts = self._protected_texts(
                base, options.get("must_preserve", [])
            )
            brief = {
                **(chapter.brief or {}),
                "_operation": job.job_type,
                "goal": options.get("goal") or (chapter.brief or {}).get("goal", ""),
                "must_preserve": protected_texts,
                "must_improve": options.get("must_improve", []),
                "forbidden_events": [
                    *(chapter.brief or {}).get("forbidden_events", []),
                    *options.get("must_not_include", []),
                ],
                "target_words": options.get("target_words", chapter.target_words),
                "pace": options.get("pace", "均衡"),
                "dialogue_ratio": options.get("dialogue_ratio", 35),
                "style_instruction": options.get("style_instruction", ""),
            }

            # Stage 0: deterministic prewrite gate. Re-run here so a queued job
            # cannot bypass policy changes made after it was accepted.
            if self._cancelled(job, chapter):
                return
            self._emit(job, index=0, stage=self.STAGES[0])
            prewrite = WritingPolicyService(self.session).contract(
                chapter, overrides=brief
            )
            if not prewrite["ready"]:
                messages = "；".join(
                    item["message"] for item in prewrite["gate"]["blockers"]
                )
                raise ValueError(f"写前门禁未通过：{messages}")

            # Stage 1: assemble context
            if self._cancelled(job, chapter):
                return
            self._emit(job, index=1, stage=self.STAGES[1])
            existing_content = (
                base.content
                if base
                and job.job_type in {"CONTINUE_CHAPTER", "REWRITE_CHAPTER"}
                else ""
            )
            context, context_sources = ContextAssembler(self.session).build(
                chapter,
                brief=brief,
                existing_content=existing_content,
            )
            time.sleep(0.05)

            policy_snapshot = context.get("writingContract") or prewrite

            # Stage 2: plot beats
            if self._cancelled(job, chapter):
                return
            self._emit(job, index=2, stage=self.STAGES[2])
            plot_plan = plan_scene_beats(
                self.session, chapter=chapter, brief=brief, context=context
            )
            brief["_plot_plan"] = plot_plan
            brief["_context"] = context
            time.sleep(0.05)

            # Stage 3: write
            if self._cancelled(job, chapter):
                return
            self._emit(job, index=3, stage=self.STAGES[3])
            model = self.model or self._model_for_novel(chapter.novel_id, chapter.id)
            content = self._generate_with_events(
                job,
                model,
                title=chapter.title,
                brief=brief,
                existing_content=existing_content,
            )

            # Stage 4: continuity skill
            if self._cancelled(job, chapter):
                return
            self._emit(job, index=4, stage=self.STAGES[4])
            continuity = run_continuity_skill(
                self.session,
                chapter=chapter,
                content=content,
                protected_texts=protected_texts,
                must_events=list(brief.get("must_events") or []),
                forbidden_events=list(brief.get("forbidden_events") or []),
            )
            # If skill reports missing protected text, append once before audit.
            for issue in continuity.get("issues") or []:
                if issue.get("type") == "锁定内容" and issue.get("evidence"):
                    text = str(issue["evidence"])
                    if text and text not in content:
                        addition = "\n\n" + text
                        content = content.rstrip() + addition
                        self._emit_content_delta(job, addition, len(job.events))

            chapter_service = ChapterService(self.session)
            version = chapter_service.create_version(
                chapter,
                content=content,
                title=chapter.title,
                source="generate" if job.job_type == "GENERATE_CHAPTER" else "rewrite",
                base_version_id=job.base_version_id,
                model_name=model.name,
                make_current=False,
                locked_ranges=base.locked_ranges if base else [],
            )
            audit_id = None
            base_is_current = chapter.current_version_id == job.base_version_id
            audit_config = self.session.scalar(
                select(AuditConfig).where(AuditConfig.novel_id == chapter.novel_id)
            )
            audit_enabled = bool(
                auto_audit
                and (audit_config is None or audit_config.enabled)
                and (audit_config is None or audit_config.auto_audit)
            )
            if audit_enabled:
                if self._cancelled(job, chapter):
                    return
                self._emit(job, index=5, stage=self.STAGES[5])
                audit = AuditService(self.session).audit(
                    chapter,
                    version,
                    update_chapter=False,
                    protected_texts=protected_texts,
                )
                audit_id = audit.id
            job.state = JobState.COMPLETED
            job.stage = "已完成"
            job.result = {
                "versionId": version.id,
                "auditId": audit_id,
                "stale": not base_is_current,
                "contextSources": context_sources,
                "contextManifest": ContextAssembler.manifest(context, context_sources),
                "plotPlan": plot_plan,
                "continuity": {
                    "pass": continuity.get("pass"),
                    "issueCount": continuity.get("issue_count"),
                    "issues": continuity.get("issues") or [],
                },
                "policySnapshot": policy_snapshot,
                "promptManifest": {
                    "ruleset": CKSKILL_RULESET_VERSION,
                    "hash": hashlib.sha256(
                        json.dumps(
                            {"brief": brief, "contract": policy_snapshot},
                            ensure_ascii=False,
                            sort_keys=True,
                            default=str,
                        ).encode("utf-8")
                    ).hexdigest(),
                    "autoAudit": audit_enabled,
                },
            }
            job.events = [*job.events, {"type": "completed", "stage": job.stage, "result": job.result, "at": utc_iso()}]
            if base_is_current:
                chapter.state = ChapterState.REVIEW_REQUIRED
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            job = self.repo.get_job(job_id)
            job.state = JobState.FAILED
            job.stage = "生成失败"
            job.error = str(exc)
            job.events = [*job.events, {"type": "failed", "error": str(exc), "at": utc_iso()}]
            chapter = self.repo.get_chapter(job.chapter_id or "")
            chapter.state = (
                ChapterState.DRAFT if chapter.current_version_id else ChapterState.PLANNED
            )
            self.session.commit()

    def _run_audit_and_rewrite(self, job: GenerationJob, chapter: Chapter) -> None:
        if not job.base_version_id:
            raise ValueError("Chapter has no version to audit")
        base = self.repo.get_version(job.base_version_id)
        config = self.session.scalar(
            select(AuditConfig).where(AuditConfig.novel_id == chapter.novel_id)
        )
        # CKSKILL requires one review round per operation. A failed review may
        # drive one targeted rewrite, then the candidate returns to the author.
        attempts_allowed = min(1, config.max_rewrite_attempts if config else 1)
        audit = AuditService(self.session).audit(chapter, base, update_chapter=False)
        options = (job.events[0].get("request", {}) if job.events else {}) or {}
        context, context_sources = ContextAssembler(self.session).build(
            chapter,
            brief={
                **(chapter.brief or {}),
                **options,
                "must_improve": audit.rewrite_requirements.get("mustImprove", []),
                "must_not_include": audit.rewrite_requirements.get(
                    "mustNotInclude", []
                ),
            },
            existing_content=base.content,
        )
        model = self.model or self._model_for_novel(chapter.novel_id, chapter.id)
        protected_texts = self._protected_texts(
            base,
            [
                *audit.rewrite_requirements.get("mustPreserve", []),
                *options.get("must_preserve", []),
            ],
        )
        latest = base
        attempts = 0

        if audit.decision != "PASS" and attempts < attempts_allowed:
            self.session.refresh(job)
            if job.cancel_requested:
                job.state = JobState.CANCELLED
                job.stage = "已取消"
                job.events = [
                    *job.events,
                    {"type": "cancelled", "stage": job.stage, "at": utc_iso()},
                ]
                self.session.commit()
                return

            attempts += 1
            job.stage = f"正在执行第 {attempts} 轮重写"
            job.events = [
                *job.events,
                {
                    "type": "progress",
                    "index": attempts,
                    "stage": job.stage,
                    "attempt": attempts,
                    "at": utc_iso(),
                },
            ]
            self.session.commit()
            self._emit_content_reset(job)
            content = self._generate_with_events(
                job,
                model,
                title=chapter.title,
                brief={
                    **chapter.brief,
                    "must_preserve": protected_texts,
                    "must_improve": audit.rewrite_requirements.get("mustImprove", []),
                    "forbidden_events": audit.rewrite_requirements.get("mustNotInclude", []),
                    "target_words": options.get("target_words", chapter.target_words),
                    "pace": options.get("pace", "均衡"),
                    "dialogue_ratio": options.get("dialogue_ratio", 35),
                    "style_instruction": options.get("style_instruction", ""),
                    "_context": context,
                },
                existing_content="",
            )
            latest = ChapterService(self.session).create_version(
                chapter,
                content=content,
                title=chapter.title,
                source="rewrite",
                base_version_id=job.base_version_id,
                model_name=model.name,
                make_current=False,
                locked_ranges=base.locked_ranges,
            )

        stale = chapter.current_version_id != job.base_version_id
        job.state = JobState.COMPLETED
        final_decision = (
            audit.decision if attempts == 0 else "REVIEW_REQUIRED"
        )
        job.stage = "已完成" if final_decision == "PASS" else "需要人工审阅"
        job.result = {
            "versionId": latest.id,
            "auditId": audit.id,
            "attempts": attempts,
            "decision": final_decision,
            "sourceAuditDecision": audit.decision,
            "reviewRounds": 1,
            "stale": stale,
            "contextSources": context_sources,
            "contextManifest": ContextAssembler.manifest(context, context_sources),
        }
        job.events = [
            *job.events,
            {
                "type": "completed",
                "stage": job.stage,
                "result": job.result,
                "at": utc_iso(),
            },
        ]
        if not stale:
            chapter.state = ChapterState.REVIEW_REQUIRED
        self.session.commit()
