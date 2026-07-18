from __future__ import annotations

import math
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .agents.models import model_config_for_role
from .agents.outline import AgentScopeOutlineAgent
from .craft import (
    PLACEHOLDER_PATTERNS,
    build_writing_contract,
    normalize_writing_profile,
    profile_readiness,
)
from .memory.outline_preview_store import get_preview, pop_preview, put_preview
from .memory.qdrant_store import delete_chunk_vectors
from .models import (
    AgentCallLog,
    Chapter,
    ChapterAudit,
    ChapterVersion,
    CharacterState,
    GenerationJob,
    LocationState,
    MemoryChunk,
    NarrativeSummary,
    Novel,
    NovelRule,
    OutlineNode,
    PlotThread,
    SkillRun,
    StoryBeat,
    StoryEntity,
    StoryEvent,
    new_id,
)


CHILD_KIND_MAP = {
    None: "volume",
    "volume": "arc",
    "arc": "chapter",
    "chapter": "scene",
    "scene": "scene",
}

_PHASE_LABELS = {
    "setup": "铺垫期",
    "build": "升级期",
    "climax": "高潮期",
    "resolve": "收尾期",
}


def _phase_for(index: int, total: int) -> str:
    """Bucket a 1-based chapter index within a volume into a pacing phase."""
    total = max(1, int(total))
    idx = max(1, int(index))
    frac = min(1.0, idx / total)
    if frac <= 0.3:
        return "setup"
    if frac <= 0.7:
        return "build"
    if frac <= 0.9:
        return "climax"
    return "resolve"


class OutlineService:
    def __init__(self, session: Session):
        self.session = session

    def delete_node(self, node_id: str) -> dict[str, Any]:
        """Delete a volume or arc together with every descendant and linked chapter data."""
        node = self.session.get(OutlineNode, node_id)
        if node is None:
            raise ValueError("outline node not found")
        if node.kind not in {"volume", "arc"}:
            raise ValueError("只能删除卷或剧情弧")

        nodes = self.session.scalars(
            select(OutlineNode).where(OutlineNode.novel_id == node.novel_id)
        ).all()
        children: dict[str, list[OutlineNode]] = {}
        for item in nodes:
            if item.parent_id:
                children.setdefault(item.parent_id, []).append(item)

        ordered: list[OutlineNode] = []

        def collect(current: OutlineNode) -> None:
            for child in children.get(current.id, []):
                collect(child)
            ordered.append(current)

        collect(node)
        node_ids = [item.id for item in ordered]
        chapter_ids = self.session.scalars(
            select(Chapter.id).where(Chapter.outline_node_id.in_(node_ids))
        ).all()
        if chapter_ids:
            chunks = self.session.scalars(
                select(MemoryChunk).where(MemoryChunk.chapter_id.in_(chapter_ids))
            ).all()
            delete_chunk_vectors(self.session, chunks)
            for model in [
                CharacterState,
                LocationState,
                MemoryChunk,
                ChapterAudit,
                GenerationJob,
                AgentCallLog,
                SkillRun,
                ChapterVersion,
                StoryEvent,
            ]:
                self.session.query(model).filter(model.chapter_id.in_(chapter_ids)).delete(
                    synchronize_session=False
                )
            self.session.query(Chapter).filter(Chapter.id.in_(chapter_ids)).delete(
                synchronize_session=False
            )
            self.session.query(NarrativeSummary).filter(
                NarrativeSummary.chapter_id.in_(chapter_ids)
            ).delete(synchronize_session=False)
        self.session.query(NarrativeSummary).filter(
            NarrativeSummary.scope_id.in_(node_ids)
        ).delete(synchronize_session=False)
        for item in ordered:
            self.session.delete(item)
        novel = self.session.get(Novel, node.novel_id)
        if novel is not None:
            self._remove_outline_artifacts(novel, node_ids)
        self.session.commit()
        return {"parentId": node.parent_id, "deletedNodes": len(ordered), "deletedChapters": len(chapter_ids)}

    def move_node(self, node_id: str, direction: str) -> dict[str, Any]:
        node = self.session.get(OutlineNode, node_id)
        if node is None:
            raise ValueError("outline node not found")
        siblings = self.session.scalars(
            select(OutlineNode)
            .where(
                OutlineNode.novel_id == node.novel_id,
                OutlineNode.parent_id == node.parent_id,
            )
            .order_by(OutlineNode.position, OutlineNode.created_at)
        ).all()
        index = next((i for i, item in enumerate(siblings) if item.id == node.id), -1)
        if index < 0:
            raise ValueError("outline node not in sibling list")
        swap_with = index - 1 if direction == "up" else index + 1
        if swap_with < 0 or swap_with >= len(siblings):
            return {
                "id": node.id,
                "moved": False,
                "reason": "already at boundary",
                "position": node.position,
            }
        a, b = siblings[index], siblings[swap_with]
        a.position, b.position = b.position, a.position
        # Normalize positions 1..n after swap to keep stable order.
        ordered = sorted(siblings, key=lambda item: (item.position, item.created_at.isoformat() if item.created_at else ""))
        for pos, item in enumerate(ordered, start=1):
            item.position = pos
        self.session.commit()
        renumbered = self.renumber_chapters(node.novel_id)
        return {
            "id": node.id,
            "moved": True,
            "direction": direction,
            "position": node.position,
            "renumberedChapters": renumbered,
        }

    def renumber_chapters(self, novel_id: str) -> int:
        """Assign chapter_index by outline tree order (volume/arc/chapter DFS)."""
        nodes = self.session.scalars(
            select(OutlineNode).where(OutlineNode.novel_id == novel_id)
        ).all()
        by_parent: dict[str | None, list[OutlineNode]] = {}
        for node in nodes:
            by_parent.setdefault(node.parent_id, []).append(node)
        for group in by_parent.values():
            group.sort(key=lambda item: (item.position, item.title))

        ordered_chapters: list[OutlineNode] = []

        def walk(parent_id: str | None) -> None:
            for child in by_parent.get(parent_id, []):
                if child.kind == "chapter":
                    ordered_chapters.append(child)
                walk(child.id)

        walk(None)

        # Two-phase renumber to avoid UNIQUE(novel_id, chapter_index) collisions.
        pairs: list[tuple[Chapter, OutlineNode, int, str]] = []
        for index, node in enumerate(ordered_chapters, start=1):
            chapter = self.session.scalar(
                select(Chapter).where(Chapter.outline_node_id == node.id)
            )
            short = node.title
            if "·" in short:
                short = short.split("·", 1)[-1].strip()
            if chapter is None:
                continue
            pairs.append((chapter, node, index, short))

        for offset, (chapter, _node, _index, _short) in enumerate(pairs):
            chapter.chapter_index = 100000 + offset
        self.session.flush()

        count = 0
        for chapter, node, index, short in pairs:
            desired_title = f"第 {index} 章 · {short}" if short else f"第 {index} 章"
            if chapter.chapter_index != index or chapter.title != short:
                chapter.chapter_index = index
                chapter.title = short or chapter.title
                count += 1
            if node.title != desired_title:
                node.title = desired_title
                count += 1
        self.session.commit()
        return count

    def generate_children(
        self,
        novel: Novel,
        *,
        parent_id: str | None = None,
        child_kind: str | None = None,
        count: int = 3,
        create_chapters: bool = True,
    ) -> dict[str, Any]:
        parent: OutlineNode | None = None
        if parent_id:
            parent = self.session.get(OutlineNode, parent_id)
            if parent is None or parent.novel_id != novel.id:
                raise ValueError("parent outline node not found")
            # Locked parents are fine: we only append children, never rewrite the parent.

        resolved_kind = child_kind or CHILD_KIND_MAP.get(
            parent.kind if parent else None, "chapter"
        )
        if resolved_kind not in {"volume", "arc", "chapter", "scene"}:
            raise ValueError("invalid child_kind")
        self._validate_parent_child(parent, resolved_kind)

        siblings = self.session.scalars(
            select(OutlineNode)
            .where(
                OutlineNode.novel_id == novel.id,
                OutlineNode.parent_id == (parent.id if parent else None),
            )
            .order_by(OutlineNode.position)
        ).all()
        # Never modify locked siblings; only append new nodes.
        existing_titles = [item.title for item in siblings]
        max_pos = max((item.position for item in siblings), default=0)

        max_chapter_index = (
            self.session.scalar(
                select(func.max(Chapter.chapter_index)).where(
                    Chapter.novel_id == novel.id
                )
            )
            or 0
        )

        novel_payload = {
            "title": novel.title,
            "genre": novel.genre,
            "coreIdea": novel.core_idea,
            "style": novel.style,
            "narrativePov": novel.narrative_pov,
            "plannedChapters": novel.planned_chapters,
            "writingProfile": novel.writing_profile or {},
        }
        parent_payload = (
            {
                "id": parent.id,
                "kind": parent.kind,
                "title": parent.title,
                "details": parent.details,
            }
            if parent
            else None
        )

        draft_count = max(0, min(200, count))
        context = self._generation_context(novel.id)
        self._require_blueprint_for_root_volume(context, parent, resolved_kind)
        context = self._outline_context(
            novel_id=novel.id,
            parent=parent,
            child_kind=resolved_kind,
            siblings=siblings,
            draft_count=draft_count,
            context=context,
        )
        drafts, draft_source, model_fallback = self._draft_nodes(
            novel_id=novel.id,
            novel_payload=novel_payload,
            parent_payload=parent_payload,
            child_kind=resolved_kind,
            count=draft_count,
            existing_titles=existing_titles,
            start_chapter_index=max_chapter_index + 1,
            context=context,
            mode="children",
        )
        self._normalize_draft_budgets(
            drafts,
            child_kind=resolved_kind,
            novel=novel,
            parent=parent,
            siblings=siblings,
        )
        self._attach_pacing(drafts, context.get("pacing") or {})

        result = self._commit_drafts(
            novel=novel,
            parent=parent,
            resolved_kind=resolved_kind,
            drafts=drafts,
            draft_source=draft_source,
            create_chapters=create_chapters,
            max_pos=max_pos,
            max_chapter_index=max_chapter_index,
            locked_sibling_count=sum(1 for item in siblings if item.locked),
        )
        if model_fallback:
            result["modelFallback"] = True
        return result

    def preview_children(
        self,
        novel: Novel,
        *,
        parent_id: str | None = None,
        child_kind: str | None = None,
        count: int = 10,
        create_chapters: bool = True,
        mode: str = "batch_chapters",
        run_coherence: bool = True,
        prior_drafts: list[dict[str, Any]] | None = None,
        chapter_offset: int = 0,
    ) -> dict[str, Any]:
        """Generate outline drafts into a TTL preview (no DB writes)."""
        parent: OutlineNode | None = None
        if parent_id:
            parent = self.session.get(OutlineNode, parent_id)
            if parent is None or parent.novel_id != novel.id:
                raise ValueError("parent outline node not found")

        resolved_kind = child_kind or CHILD_KIND_MAP.get(
            parent.kind if parent else None, "chapter"
        )
        if mode == "batch_chapters":
            resolved_kind = "chapter"
            if parent is None:
                raise ValueError("请先选择一个剧情弧，再生成章节细纲")
            # A chapter selection targets its owning arc, never an arbitrary sibling.
            if parent and parent.kind == "chapter" and parent.parent_id:
                parent = self.session.get(OutlineNode, parent.parent_id) or parent
            if parent.kind != "arc":
                raise ValueError("请先在目标分卷下创建并选择一个剧情弧，再生成章节细纲")

        if resolved_kind not in {"volume", "arc", "chapter", "scene"}:
            raise ValueError("invalid child_kind")
        self._validate_parent_child(parent, resolved_kind)

        siblings = self.session.scalars(
            select(OutlineNode)
            .where(
                OutlineNode.novel_id == novel.id,
                OutlineNode.parent_id == (parent.id if parent else None),
            )
            .order_by(OutlineNode.position)
        ).all()
        existing_titles = [item.title for item in siblings]
        prior_drafts = [item for item in (prior_drafts or []) if isinstance(item, dict)]
        existing_titles.extend(
            str(item.get("title") or "").strip()
            for item in prior_drafts
            if str(item.get("title") or "").strip()
        )
        max_chapter_index = (
            self.session.scalar(
                select(func.max(Chapter.chapter_index)).where(Chapter.novel_id == novel.id)
            )
            or 0
        )

        novel_payload = {
            "title": novel.title,
            "genre": novel.genre,
            "coreIdea": novel.core_idea,
            "style": novel.style,
            "narrativePov": novel.narrative_pov,
            "plannedChapters": novel.planned_chapters,
            "writingProfile": novel.writing_profile or {},
        }
        parent_payload = (
            {
                "id": parent.id,
                "kind": parent.kind,
                "title": parent.title,
                "details": parent.details,
            }
            if parent
            else None
        )
        context = self._generation_context(novel.id)
        self._require_blueprint_for_root_volume(context, parent, resolved_kind)
        draft_count = max(0, min(200, count))
        context = self._outline_context(
            novel_id=novel.id,
            parent=parent,
            child_kind=resolved_kind,
            siblings=siblings,
            draft_count=draft_count,
            chapter_offset=chapter_offset,
            context=context,
        )
        if prior_drafts:
            context["prior_chapter_briefs"] = (
                list(context.get("prior_chapter_briefs") or []) + prior_drafts
            )[-12:]
        drafts, draft_source, model_fallback = self._draft_nodes(
            novel_id=novel.id,
            novel_payload=novel_payload,
            parent_payload=parent_payload,
            child_kind=resolved_kind,
            count=draft_count,
            existing_titles=existing_titles,
            start_chapter_index=max_chapter_index + 1 + max(0, chapter_offset),
            context=context,
            mode=mode if mode in {"batch_chapters", "children", "master_outline"} else "children",
        )
        if draft_count > 0 and len(drafts) < draft_count:
            raise ValueError("云端模型返回的大纲数量不足，请重试。")
        self._normalize_draft_budgets(
            drafts,
            child_kind=resolved_kind,
            novel=novel,
            parent=parent,
            siblings=siblings,
        )
        self._attach_pacing(drafts, context.get("pacing") or {})

        coherence: dict[str, Any] = {}
        if run_coherence:
            coherence = self._run_coherence(
                novel_id=novel.id,
                nodes=drafts,
                existing_titles=existing_titles,
                prior_briefs=context.get("prior_chapter_briefs") or [],
                volume_plan=context.get("volume_plan") or {},
                unresolved_foreshadow=context.get("unresolved_foreshadow") or [],
                child_kind=resolved_kind,
            )

        preview = put_preview(
            self.session,
            novel_id=novel.id,
            parent_id=parent.id if parent else None,
            child_kind=resolved_kind,
            create_chapters=bool(create_chapters and resolved_kind == "chapter"),
            nodes=drafts,
            source=draft_source,
            coherence=coherence,
            mode=mode,
            meta={"modelFallback": bool(model_fallback)},
        )
        return {
            "previewId": preview["previewId"],
            "parentId": preview["parentId"],
            "childKind": preview["childKind"],
            "createChapters": preview["createChapters"],
            "draftSource": draft_source,
            "mode": mode,
            "nodes": preview["nodes"],
            "coherence": coherence,
            "modelFallback": bool(model_fallback),
            "expiresAt": preview["expiresAt"],
        }

    def master_preview(
        self,
        novel: Novel,
        *,
        volume_count: int | None = None,
        chapter_count: int | None = None,
        run_coherence: bool = True,
    ) -> dict[str, Any]:
        """Preview a top-level volume plan after the story blueprint is confirmed."""
        if model_config_for_role(self.session, novel.id, "大纲") is None and model_config_for_role(
            self.session, novel.id, "写作"
        ) is None:
            raise ValueError("请先连接可用的云端模型，再生成全书规划。")
        context = self._generation_context(novel.id)
        if not context.get("blueprint"):
            raise ValueError("请先生成并确认故事蓝图，再生成分卷总纲")

        existing_volume = self.session.scalars(
            select(OutlineNode)
            .where(OutlineNode.novel_id == novel.id, OutlineNode.kind == "volume")
            .order_by(OutlineNode.position)
        ).first()
        if existing_volume is not None:
            raise ValueError("已存在分卷总纲；请选择一个分卷生成剧情弧，或用“生成下级”追加分卷")

        from .agents.blueprint import suggested_volume_count

        fallback_suggestion = suggested_volume_count(novel.planned_chapters)
        blueprint = context.get("blueprint") or {}
        blueprint_stages = [
            str(item).strip()
            for item in (blueprint.get("arcs_outline") or [])
            if str(item).strip()
        ]
        min_reasonable = max(1, math.ceil(max(1, novel.planned_chapters) / 100))
        max_reasonable = min(12, max(min_reasonable, math.ceil(novel.planned_chapters / 30)))
        if volume_count is not None:
            count = max(1, min(12, int(volume_count)))
            count_source = "explicit"
        elif min_reasonable <= len(blueprint_stages) <= max_reasonable:
            # The blueprint itself is AI-generated and already identifies the
            # book's natural narrative stages. Use those boundaries as the
            # volume count instead of asking a second model call to re-decide.
            count = len(blueprint_stages)
            count_source = "blueprint_ai"
        else:
            count = 0
            count_source = "ai"
        if count <= 0:
            count = fallback_suggestion
            count_source = "fallback"
        stages = blueprint_stages[:count]
        if len(stages) < count:
            stages.extend(f"全书第 {index + 1} 阶段" for index in range(len(stages), count))
        skeletons = self._volume_skeletons(novel, stages)
        preview = put_preview(
            self.session,
            novel_id=novel.id,
            parent_id=None,
            child_kind="volume",
            create_chapters=False,
            nodes=skeletons,
            source="blueprint",
            mode="master_outline",
            meta={"progressiveEnrichment": True},
        )
        return {
            "previewId": preview["previewId"],
            "parentId": None,
            "childKind": "volume",
            "createChapters": False,
            "draftSource": "blueprint",
            "mode": "master_outline",
            "nodes": preview["nodes"],
            "coherence": {},
            "modelFallback": False,
            "expiresAt": preview["expiresAt"],
            "master": True,
            "stage": "volumes",
            "suggestedVolumeCount": len(skeletons),
            "volumeCountSource": count_source,
            "blueprintStageCount": len(blueprint_stages),
            "plannedChapters": novel.planned_chapters,
            "enrichmentPending": True,
        }

    def enrich_master_volume(
        self, novel: Novel, *, preview_id: str, index: int
    ) -> dict[str, Any]:
        """Generate full details for one fast master-outline skeleton."""
        record = get_preview(self.session, preview_id, novel_id=novel.id)
        if record is None:
            raise ValueError("preview not found or expired")
        if record.get("mode") != "master_outline" or record.get("childKind") != "volume":
            raise ValueError("preview is not a master volume plan")
        nodes = list(record.get("nodes") or [])
        if index < 0 or index >= len(nodes):
            raise ValueError("volume index out of range")
        seed = nodes[index]
        if not isinstance(seed, dict):
            raise ValueError("invalid volume skeleton")

        context = self._generation_context(novel.id)
        seed_details = dict(seed.get("details") or {})
        context["volume_plan"] = {
            **seed_details,
            "title": str(seed.get("title") or ""),
            "instruction": "补全这一卷，保持卷名、阶段目标和章节预算，不要生成其他卷",
        }
        novel_payload = {
            "title": novel.title,
            "genre": novel.genre,
            "coreIdea": novel.core_idea,
            "style": novel.style,
            "narrativePov": novel.narrative_pov,
            "plannedChapters": novel.planned_chapters,
        }
        drafts, source, model_fallback = self._draft_nodes(
            novel_id=novel.id,
            novel_payload=novel_payload,
            parent_payload=None,
            child_kind="volume",
            count=1,
            existing_titles=[
                str(node.get("title") or "")
                for position, node in enumerate(nodes)
                if position != index and isinstance(node, dict)
            ],
            start_chapter_index=1,
            context=context,
            mode="master_outline_enrich",
        )
        draft = drafts[0] if drafts else {}
        details = {**seed_details, **dict(draft.get("details") or {})}
        details["planned_chapters"] = self._planned_chapters(seed_details)
        return {
            "index": index,
            "node": {
                "kind": "volume",
                "title": str(seed.get("title") or draft.get("title") or f"第 {index + 1} 卷"),
                "details": details,
                "selected": seed.get("selected", True),
            },
            "draftSource": source,
            "modelFallback": model_fallback,
        }

    def _volume_skeletons(
        self, novel: Novel, stages: list[str]
    ) -> list[dict[str, Any]]:
        skeletons: list[dict[str, Any]] = []
        weights: list[int] = []
        for index, stage in enumerate(stages, start=1):
            range_match = re.search(r"(\d+)\s*[-—~至]\s*(\d+)\s*章", stage)
            weight = 1
            if range_match:
                weight = max(1, int(range_match.group(2)) - int(range_match.group(1)) + 1)
            weights.append(weight)
            heading = re.split(r"[（(:：]", stage, maxsplit=1)[0].strip()
            title = heading if "卷" in heading else f"第 {index} 卷 · {heading[:24]}"
            summary = re.split(r"[：:]", stage, maxsplit=1)[-1].strip() or stage
            skeletons.append(
                {
                    "kind": "volume",
                    "title": title,
                    "details": {
                        "stage_goal": summary,
                        "arc_summary": summary,
                        "planned_chapters": weight,
                        "key_turns": [],
                        "core_conflict": "",
                        "foreshadow_plant": [],
                        "foreshadow_payoff": [],
                        "characters": [],
                        "locations": [],
                        "plot_arcs": [],
                        "hook": "",
                    },
                }
            )
        budgets = self._allocate_budget(novel.planned_chapters, weights)
        for node, budget in zip(skeletons, budgets, strict=True):
            node["details"]["planned_chapters"] = budget
        return skeletons

    def complete_chapter_contract(
        self,
        chapter: Chapter,
        *,
        overrides: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fill only missing CKSKILL contract fields before chapter generation."""
        novel = self.session.get(Novel, chapter.novel_id)
        if novel is None:
            raise ValueError("novel not found")

        if not profile_readiness(novel.writing_profile)["ready"]:
            from .services_blueprint import BlueprintService

            blueprint_service = BlueprintService(self.session)
            blueprint = blueprint_service.get_blueprint(novel.id)
            if blueprint is None:
                preview = blueprint_service.preview(novel)
                blueprint_service.commit(novel, preview_id=preview["previewId"])
            else:
                blueprint_service.commit(novel, blueprint=blueprint)
            self.session.refresh(novel)

        current = dict(chapter.brief or {})
        values = dict(overrides or {})
        for key in ("goal", "conflict"):
            value = values.get(key)
            if self._contract_value_missing(current.get(key)) and str(value or "").strip():
                current[key] = value

        initial = build_writing_contract(
            profile=novel.writing_profile,
            genre=novel.genre,
            chapter_index=chapter.chapter_index,
            chapter_title=chapter.title,
            brief=current,
        )
        if initial["gate"]["status"] == "pass":
            return {"changed": False, "source": "existing", "contract": initial}

        node = (
            self.session.get(OutlineNode, chapter.outline_node_id)
            if chapter.outline_node_id
            else None
        )
        generated: dict[str, Any] = {}
        source = "model"
        if node is not None and node.novel_id == novel.id and not node.locked:
            preview_id = ""
            try:
                preview = self.preview_regenerate_node(
                    novel,
                    node_id=node.id,
                    run_coherence=False,
                )
                preview_id = str(preview.get("previewId") or "")
                nodes = preview.get("nodes") or []
                if nodes and isinstance(nodes[0], dict):
                    generated = dict(nodes[0].get("details") or {})
                    source = str(preview.get("draftSource") or "model")
            finally:
                if preview_id:
                    self.discard_preview(novel.id, preview_id)

        parent = (
            self.session.get(OutlineNode, node.parent_id)
            if node is not None and node.parent_id
            else None
        )
        if not generated:
            parent_payload = (
                {
                    "id": parent.id,
                    "kind": parent.kind,
                    "title": parent.title,
                    "details": parent.details,
                }
                if parent is not None
                else None
            )
            drafts, source, _ = self._draft_nodes(
                novel_id=novel.id,
                novel_payload={
                "title": novel.title,
                "genre": novel.genre,
                "coreIdea": novel.core_idea,
                "plannedChapters": novel.planned_chapters,
                },
                parent_payload=parent_payload,
                child_kind="chapter",
                count=1,
                existing_titles=[],
                start_chapter_index=chapter.chapter_index,
                context={},
                mode="batch_chapters",
            )
            if drafts:
                generated = dict(drafts[0].get("details") or {})

        def completed_value(key: str, default: Any = "") -> Any:
            value = generated.get(key)
            return default if self._contract_value_missing(value) else value

        merged = dict(current)
        scalar_keys = (
            "goal",
            "conflict",
            "obstacle",
            "cost",
            "time_anchor",
            "chapter_span",
            "gap_from_previous",
            "countdown",
            "cbn",
            "cen",
            "highlight",
            "twist",
            "hook",
            "chapter_end_open_question",
            "strand",
            "antagonist_level",
            "pov_character",
            "chapter_change",
        )
        for key in scalar_keys:
            if self._contract_value_missing(merged.get(key)):
                merged[key] = completed_value(key)

        list_keys = (
            "must_events",
            "forbidden_events",
            "characters",
            "locations",
            "foreshadow_plant",
            "foreshadow_payoff",
        )
        for key in list_keys:
            if self._contract_value_missing(merged.get(key)):
                value = completed_value(key, [])
                merged[key] = list(value) if isinstance(value, list) else []

        cpns = merged.get("cpns") if isinstance(merged.get("cpns"), list) else []
        if not 2 <= len(cpns) <= 4 or self._contract_value_missing(cpns):
            replacement = generated.get("cpns") or []
            merged["cpns"] = list(replacement)[:4] if isinstance(replacement, list) else []

        must_cover = (
            merged.get("must_cover_nodes")
            if isinstance(merged.get("must_cover_nodes"), list)
            else []
        )
        if not must_cover or self._contract_value_missing(must_cover):
            must_cover = completed_value("must_cover_nodes", [])
        merged["must_cover_nodes"] = list(must_cover)[:4]

        forbidden_zones = (
            merged.get("forbidden_zones")
            if isinstance(merged.get("forbidden_zones"), list)
            else []
        )
        if not forbidden_zones:
            forbidden_zones = completed_value("forbidden_zones", [])
        merged["forbidden_zones"] = list(forbidden_zones)[:5]

        chapter.brief = merged
        if node is not None and node.novel_id == novel.id:
            node.details = dict(merged)
        self.session.commit()

        contract = build_writing_contract(
            profile=novel.writing_profile,
            genre=novel.genre,
            chapter_index=chapter.chapter_index,
            chapter_title=chapter.title,
            brief={**merged, **values},
        )
        return {"changed": merged != current, "source": source, "contract": contract}

    @staticmethod
    def _contract_value_missing(value: Any) -> bool:
        if value in (None, "", [], {}):
            return True
        if isinstance(value, dict):
            return any(OutlineService._contract_value_missing(item) for item in value.values())
        if isinstance(value, (list, tuple, set)):
            return any(OutlineService._contract_value_missing(item) for item in value)
        text = str(value).strip()
        return bool(text and any(pattern.search(text) for pattern in PLACEHOLDER_PATTERNS))

    def preview_regenerate_node(
        self,
        novel: Novel,
        *,
        node_id: str,
        run_coherence: bool = True,
    ) -> dict[str, Any]:
        """Regenerate outline details for one existing node (preview only)."""
        node = self.session.get(OutlineNode, node_id)
        if node is None or node.novel_id != novel.id:
            raise ValueError("outline node not found")
        if node.locked:
            raise ValueError("节点已锁定，无法重新生成大纲")

        parent = self.session.get(OutlineNode, node.parent_id) if node.parent_id else None
        siblings = self.session.scalars(
            select(OutlineNode)
            .where(
                OutlineNode.novel_id == novel.id,
                OutlineNode.parent_id == node.parent_id,
                OutlineNode.id != node.id,
            )
            .order_by(OutlineNode.position)
        ).all()
        existing_titles = [item.title for item in siblings]

        chapter = self.session.scalar(
            select(Chapter).where(Chapter.outline_node_id == node.id)
        )
        start_index = chapter.chapter_index if chapter is not None else 1

        novel_payload = {
            "title": novel.title,
            "genre": novel.genre,
            "coreIdea": novel.core_idea,
            "style": novel.style,
            "narrativePov": novel.narrative_pov,
            "plannedChapters": novel.planned_chapters,
        }
        parent_payload = (
            {
                "id": parent.id,
                "kind": parent.kind,
                "title": parent.title,
                "details": parent.details,
            }
            if parent
            else None
        )
        # Pass current node as soft context so model rewrites rather than clones vaguely.
        current_brief = {
            "title": node.title,
            "goal": (node.details or {}).get("stage_goal")
            if node.kind == "volume"
            else (node.details or {}).get("goal") or "",
            "hook": (node.details or {}).get("hook") or "",
            "highlight": (node.details or {}).get("highlight") or "",
            "twist": (node.details or {}).get("twist") or "",
        }
        context = self._generation_context(novel.id)
        prior = list(context.get("prior_chapter_briefs") or [])
        # Prefer regenerate around this chapter's slot.
        prior = [p for p in prior if p.get("title") != node.title][-8:]
        prior.append(current_brief)
        context = {**context, "prior_chapter_briefs": prior}
        if node.kind == "chapter":
            all_siblings = self.session.scalars(
                select(OutlineNode)
                .where(
                    OutlineNode.novel_id == novel.id,
                    OutlineNode.parent_id == node.parent_id,
                )
                .order_by(OutlineNode.position)
            ).all()
            node_index = next(
                (index for index, item in enumerate(all_siblings) if item.id == node.id),
                len(all_siblings),
            )
            chapters_before = sum(
                1 for item in all_siblings[:node_index] if item.kind == "chapter"
            )
            volume_plan = self._volume_plan_for_parent(novel.id, parent)
            arc_plan = self._arc_plan_for_parent(parent)
            context = {
                **context,
                "volume_plan": volume_plan,
                "arc_plan": arc_plan,
                "pacing": self._pacing_for(
                    volume_plan=volume_plan,
                    arc_plan=arc_plan,
                    existing_chapter_count=chapters_before,
                    batch_total=1,
                ),
            }
        elif node.kind in {"arc", "scene"}:
            context = self._outline_context(
                novel_id=novel.id,
                parent=parent,
                child_kind=node.kind,
                siblings=siblings,
                draft_count=1,
                context=context,
            )

        drafts, draft_source, model_fallback = self._draft_nodes(
            novel_id=novel.id,
            novel_payload=novel_payload,
            parent_payload=parent_payload,
            child_kind=node.kind,
            count=1,
            existing_titles=existing_titles,
            start_chapter_index=start_index,
            context=context,
            mode="regenerate_node",
        )
        self._attach_pacing(drafts, context.get("pacing") or {})
        if not drafts:
            raise ValueError("重新生成失败：模型未返回节点")

        draft = dict(drafts[0])
        # Keep chapter number stability when possible.
        if node.kind == "chapter" and chapter is not None:
            short = str(draft.get("title") or "").strip()
            if "·" in short:
                short = short.split("·", 1)[-1].strip()
            if not short:
                short = node.title.split("·", 1)[-1].strip() if "·" in node.title else node.title
            draft["title"] = f"第 {chapter.chapter_index} 章 · {short}"
        draft["selected"] = True
        draft["kind"] = node.kind

        coherence: dict[str, Any] = {}
        if run_coherence:
            coherence = self._run_coherence(
                novel_id=novel.id,
                nodes=[draft],
                existing_titles=existing_titles,
                prior_briefs=context.get("prior_chapter_briefs") or [],
                volume_plan=context.get("volume_plan") or {},
                unresolved_foreshadow=context.get("unresolved_foreshadow") or [],
                child_kind=node.kind,
            )

        preview = put_preview(
            self.session,
            novel_id=novel.id,
            parent_id=node.parent_id,
            child_kind=node.kind,
            create_chapters=False,
            nodes=[draft],
            source=draft_source,
            coherence=coherence,
            mode="regenerate_node",
            meta={
                "targetNodeId": node.id,
                "replace": True,
                "modelFallback": bool(model_fallback),
            },
        )
        return {
            "previewId": preview["previewId"],
            "parentId": preview["parentId"],
            "childKind": preview["childKind"],
            "createChapters": False,
            "draftSource": draft_source,
            "mode": "regenerate_node",
            "targetNodeId": node.id,
            "nodes": preview["nodes"],
            "coherence": coherence,
            "modelFallback": bool(model_fallback),
            "expiresAt": preview["expiresAt"],
        }

    def commit_preview(
        self,
        novel: Novel,
        *,
        preview_id: str,
        nodes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Write selected preview nodes to DB and drop the preview."""
        record = get_preview(self.session, preview_id, novel_id=novel.id)
        if record is None:
            raise ValueError("preview not found or expired")

        draft_nodes = nodes if nodes is not None else list(record.get("nodes") or [])
        selected = [
            n
            for n in draft_nodes
            if isinstance(n, dict) and n.get("selected", True) and str(n.get("title") or "").strip()
        ]
        if not selected:
            raise ValueError("no selected nodes to commit")

        # Replace existing node details (regenerate 本章大纲).
        meta = record.get("meta") or {}
        if record.get("mode") == "regenerate_node" or meta.get("replace"):
            target_id = str(meta.get("targetNodeId") or "")
            target = self.session.get(OutlineNode, target_id) if target_id else None
            if target is None or target.novel_id != novel.id:
                raise ValueError("重新生成目标节点不存在")
            if target.locked:
                raise ValueError("节点已锁定，无法覆盖大纲")
            draft = selected[0]
            new_title = str(draft.get("title") or target.title).strip()
            new_details = draft.get("details") if isinstance(draft.get("details"), dict) else {}
            chapter = self.session.scalar(
                select(Chapter).where(Chapter.outline_node_id == target.id)
            )
            profile = normalize_writing_profile(novel.writing_profile)
            if target.kind == "chapter" and profile["strict_workflow"]:
                contract = build_writing_contract(
                    profile=profile,
                    genre=novel.genre,
                    chapter_index=chapter.chapter_index if chapter is not None else 0,
                    chapter_title=new_title or target.title,
                    brief=new_details,
                )
                if not contract["ready"]:
                    messages = "、".join(
                        item["message"] for item in contract["gate"]["blockers"]
                    )
                    raise ValueError(f"规划门禁未通过：{messages}")
            target.title = new_title or target.title
            target.details = new_details or {}
            if chapter is not None:
                short = target.title
                if "·" in short:
                    short = short.split("·", 1)[-1].strip()
                chapter.title = short or chapter.title
                chapter.brief = dict(target.details or {})
            self._sync_outline_artifacts(novel, target, chapter=chapter, replace_source=True)
            self.session.commit()
            pop_preview(self.session, preview_id, novel_id=novel.id)
            return {
                "parentId": target.parent_id,
                "childKind": target.kind,
                "draftSource": str(record.get("source") or "skill"),
                "mode": "regenerate_node",
                "replacedNodeId": target.id,
                "created": [
                    {
                        "id": target.id,
                        "kind": target.kind,
                        "title": target.title,
                        "locked": target.locked,
                        "details": target.details,
                    }
                ],
                "chaptersCreated": 0,
                "chaptersUpdated": 1 if chapter is not None else 0,
                "skippedLockedSiblings": 0,
                "previewId": preview_id,
                "coherence": record.get("coherence") or {},
                "modelFallback": bool(meta.get("modelFallback")),
            }

        parent_id = record.get("parentId")
        parent = self.session.get(OutlineNode, parent_id) if parent_id else None
        if parent is not None and parent.novel_id != novel.id:
            raise ValueError("parent outline node not found")

        resolved_kind = str(record.get("childKind") or "chapter")
        self._validate_parent_child(parent, resolved_kind)
        siblings = self.session.scalars(
            select(OutlineNode)
            .where(
                OutlineNode.novel_id == novel.id,
                OutlineNode.parent_id == (parent.id if parent else None),
            )
            .order_by(OutlineNode.position)
        ).all()
        max_pos = max((item.position for item in siblings), default=0)
        max_chapter_index = (
            self.session.scalar(
                select(func.max(Chapter.chapter_index)).where(Chapter.novel_id == novel.id)
            )
            or 0
        )
        self._normalize_draft_budgets(
            selected,
            child_kind=resolved_kind,
            novel=novel,
            parent=parent,
            siblings=siblings,
        )

        result = self._commit_drafts(
            novel=novel,
            parent=parent,
            resolved_kind=resolved_kind,
            drafts=selected,
            draft_source=str(record.get("source") or "skill"),
            create_chapters=bool(record.get("createChapters")),
            max_pos=max_pos,
            max_chapter_index=max_chapter_index,
            locked_sibling_count=sum(1 for item in siblings if item.locked),
        )
        pop_preview(self.session, preview_id, novel_id=novel.id)
        result["previewId"] = preview_id
        result["coherence"] = record.get("coherence") or {}
        result["modelFallback"] = bool((record.get("meta") or {}).get("modelFallback"))
        return result

    def discard_preview(self, novel_id: str, preview_id: str) -> bool:
        return pop_preview(self.session, preview_id, novel_id=novel_id) is not None

    def _commit_drafts(
        self,
        *,
        novel: Novel,
        parent: OutlineNode | None,
        resolved_kind: str,
        drafts: list[dict[str, Any]],
        draft_source: str,
        create_chapters: bool,
        max_pos: int,
        max_chapter_index: int,
        locked_sibling_count: int,
    ) -> dict[str, Any]:
        if resolved_kind == "chapter":
            profile = normalize_writing_profile(novel.writing_profile)
            if profile["strict_workflow"]:
                failures: list[str] = []
                for index, draft in enumerate(drafts, start=1):
                    title = str(draft.get("title") or f"第 {max_chapter_index + index} 章")
                    contract = build_writing_contract(
                        profile=profile,
                        genre=novel.genre,
                        chapter_index=max_chapter_index + index,
                        chapter_title=title,
                        brief=draft.get("details") if isinstance(draft.get("details"), dict) else {},
                    )
                    if not contract["ready"]:
                        messages = "、".join(
                            item["message"] for item in contract["gate"]["blockers"]
                        )
                        failures.append(f"{title}：{messages}")
                if failures:
                    raise ValueError("规划门禁未通过：" + "；".join(failures))
        created: list[OutlineNode] = []
        chapters_created: list[Chapter] = []
        for index, draft in enumerate(drafts, start=1):
            chapter: Chapter | None = None
            node = OutlineNode(
                id=new_id(),
                workspace_id=novel.workspace_id,
                novel_id=novel.id,
                parent_id=parent.id if parent else None,
                kind=resolved_kind,
                title=str(draft.get("title") or f"未命名 {index}").strip(),
                position=max_pos + index,
                locked=False,
                details=draft.get("details") or {},
            )
            self.session.add(node)
            self.session.flush()
            created.append(node)

            if resolved_kind == "chapter" and create_chapters:
                chapter_index = max_chapter_index + index
                short_title = node.title
                if "·" in short_title:
                    short_title = short_title.split("·", 1)[-1].strip()
                chapter = Chapter(
                    workspace_id=novel.workspace_id,
                    novel_id=novel.id,
                    outline_node_id=node.id,
                    chapter_index=chapter_index,
                    title=short_title or f"第 {chapter_index} 章",
                    state="PLANNED",
                    brief=draft.get("details") or {},
                    target_words=3500,
                )
                self.session.add(chapter)
                chapters_created.append(chapter)

            self._sync_outline_artifacts(novel, node, chapter=chapter)

        self.session.commit()
        return {
            "parentId": parent.id if parent else None,
            "childKind": resolved_kind,
            "draftSource": draft_source,
            "created": [
                {
                    "id": node.id,
                    "kind": node.kind,
                    "title": node.title,
                    "locked": node.locked,
                    "details": node.details,
                }
                for node in created
            ],
            "chaptersCreated": len(chapters_created),
            "skippedLockedSiblings": locked_sibling_count,
        }

    def _sync_outline_artifacts(
        self,
        novel: Novel,
        node: OutlineNode,
        *,
        chapter: Chapter | None = None,
        replace_source: bool = False,
    ) -> None:
        """Sync a committed outline node into the story bible and plot views."""
        if replace_source:
            self._remove_outline_artifacts(novel, [node.id])

        details = node.details or {}
        for entity_type, key in (("character", "characters"), ("location", "locations")):
            names = {
                str(value).strip()
                for value in (details.get(key) or [])
                if str(value).strip()
            }
            for name in names:
                entity = self.session.scalar(
                    select(StoryEntity).where(
                        StoryEntity.novel_id == novel.id,
                        StoryEntity.entity_type == entity_type,
                        StoryEntity.name == name,
                    )
                )
                if entity is None:
                    self.session.add(
                        StoryEntity(
                            workspace_id=novel.workspace_id,
                            novel_id=novel.id,
                            entity_type=entity_type,
                            name=name,
                            summary=f"由大纲「{node.title}」生成",
                            data={"outlineGenerated": True, "outlineNodeIds": [node.id]},
                        )
                    )
                    continue

                data = dict(entity.data or {})
                sources = [str(value) for value in data.get("outlineNodeIds") or []]
                if node.id not in sources:
                    data["outlineNodeIds"] = [*sources, node.id]
                    entity.data = data

        characters = [str(value).strip() for value in (details.get("characters") or []) if str(value).strip()]
        locations = [str(value).strip() for value in (details.get("locations") or []) if str(value).strip()]
        chapter_label = node.title
        chapter_id = getattr(chapter, "id", None)
        event_texts = details.get("must_events") or details.get("turning_points") or []
        for index, action in enumerate(event_texts):
            action = str(action).strip()
            if not action:
                continue
            self.session.add(
                StoryEvent(
                    workspace_id=novel.workspace_id,
                    novel_id=novel.id,
                    chapter_id=chapter_id,
                    source_outline_node_id=node.id,
                    story_time=chapter_label,
                    sequence=node.position * 100 + index,
                    subjects=characters,
                    action=action,
                    location=locations[0] if locations else "",
                    consequences=str(details.get("hook") or details.get("closing_state") or ""),
                )
            )
        for beat_type, key in (("highlight", "highlight"), ("twist", "twist")):
            text = str(details.get(key) or "").strip()
            if text:
                self.session.add(
                    StoryBeat(
                        workspace_id=novel.workspace_id,
                        novel_id=novel.id,
                        chapter_label=chapter_label,
                        beat_type=beat_type,
                        data={"text": text, "characters": " · ".join(characters)},
                        source_outline_node_id=node.id,
                    )
                )
        for name in details.get("foreshadow_plant") or []:
            self._sync_plot_thread(novel, node, str(name).strip(), "planted")
        for name in details.get("foreshadow_payoff") or []:
            self._sync_plot_thread(novel, node, str(name).strip(), "paid")

    def _sync_plot_thread(
        self, novel: Novel, node: OutlineNode, name: str, status: str
    ) -> None:
        if not name:
            return
        thread = self.session.scalar(
            select(PlotThread).where(
                PlotThread.novel_id == novel.id,
                PlotThread.name == name,
            )
        )
        if thread is None:
            self.session.add(
                PlotThread(
                    workspace_id=novel.workspace_id,
                    novel_id=novel.id,
                    name=name,
                    kind="foreshadowing",
                    status=status,
                    planted=node.title if status == "planted" else "",
                    payoff=node.title if status == "paid" else "",
                    importance="中",
                    latest=f"大纲：{node.title}",
                    source_outline_node_id=node.id,
                )
            )
        elif status == "paid":
            thread.status = "paid"
            thread.payoff = node.title
            thread.latest = f"大纲：{node.title}（已回收）"

    def _remove_outline_artifacts(self, novel: Novel, node_ids: list[str]) -> None:
        """Remove plot records and entity provenance created by deleted outline nodes."""
        source_ids = set(node_ids)
        if not source_ids:
            return
        for model in (StoryEvent, StoryBeat):
            self.session.query(model).filter(
                model.novel_id == novel.id,
                model.source_outline_node_id.in_(source_ids),
            ).delete(synchronize_session=False)
        self.session.query(PlotThread).filter(
            PlotThread.novel_id == novel.id,
            PlotThread.source_outline_node_id.in_(source_ids),
        ).delete(synchronize_session=False)
        entities = self.session.scalars(
            select(StoryEntity).where(
                StoryEntity.novel_id == novel.id,
                StoryEntity.entity_type.in_(("character", "location")),
            )
        ).all()
        for entity in entities:
            data = dict(entity.data or {})
            sources = [str(value) for value in data.get("outlineNodeIds") or []]
            remaining = [source for source in sources if source not in source_ids]
            if remaining == sources:
                continue
            if remaining:
                data["outlineNodeIds"] = remaining
                entity.data = data
            elif data.get("outlineGenerated") is True and not entity.locked_fields:
                self.session.query(CharacterState).filter(
                    CharacterState.entity_id == entity.id
                ).delete(synchronize_session=False)
                self.session.query(LocationState).filter(
                    LocationState.entity_id == entity.id
                ).delete(synchronize_session=False)
                self.session.delete(entity)
            else:
                data.pop("outlineNodeIds", None)
                entity.data = data

    def _validate_parent_child(
        self, parent: OutlineNode | None, child_kind: str
    ) -> None:
        expected = CHILD_KIND_MAP.get(parent.kind if parent else None)
        if expected == child_kind:
            return
        parent_label = parent.title if parent else "根目录"
        expected_label = {
            "volume": "分卷",
            "arc": "剧情弧",
            "chapter": "章节",
            "scene": "场景",
        }.get(expected or "", expected or "下级节点")
        raise ValueError(f"“{parent_label}”只能生成{expected_label}")

    def _require_blueprint_for_root_volume(
        self,
        context: dict[str, Any],
        parent: OutlineNode | None,
        child_kind: str,
    ) -> None:
        if parent is None and child_kind == "volume" and not context.get("blueprint"):
            raise ValueError("请先生成并确认故事蓝图，再生成分卷总纲")

    @staticmethod
    def _planned_chapters(details: dict[str, Any] | None) -> int:
        try:
            return max(0, int((details or {}).get("planned_chapters") or 0))
        except (TypeError, ValueError):
            return 0

    def _effective_existing_budget(
        self, siblings: list[OutlineNode], child_kind: str
    ) -> int:
        """Use explicit budgets when available, otherwise infer old-tree usage.

        Older projects predate `planned_chapters`. Counting their descendant
        chapter nodes prevents a newly appended volume or arc from receiving the
        entire book's remaining plan as if the old tree were empty.
        """
        relevant = [node for node in siblings if node.kind == child_kind]
        explicit = sum(self._planned_chapters(node.details) for node in relevant)
        missing = [node for node in relevant if self._planned_chapters(node.details) == 0]
        if not missing:
            return explicit

        novel_id = missing[0].novel_id
        all_nodes = self.session.scalars(
            select(OutlineNode).where(OutlineNode.novel_id == novel_id)
        ).all()
        by_parent: dict[str | None, list[OutlineNode]] = {}
        for node in all_nodes:
            by_parent.setdefault(node.parent_id, []).append(node)

        def descendant_chapters(parent_id: str, seen: set[str]) -> int:
            if parent_id in seen:
                return 0
            next_seen = {*seen, parent_id}
            total = 0
            for child in by_parent.get(parent_id, []):
                if child.kind == "chapter":
                    total += 1
                total += descendant_chapters(child.id, next_seen)
            return total

        return explicit + sum(descendant_chapters(node.id, set()) for node in missing)

    @staticmethod
    def _allocate_budget(total: int, weights: list[int]) -> list[int]:
        if not weights:
            return []
        total = max(total, len(weights))
        remaining = total - len(weights)
        normalized = [max(1, int(weight)) for weight in weights]
        weight_sum = sum(normalized)
        raw = [remaining * weight / weight_sum for weight in normalized]
        extra = [int(value) for value in raw]
        remainder = remaining - sum(extra)
        order = sorted(
            range(len(weights)),
            key=lambda index: (raw[index] - extra[index], -index),
            reverse=True,
        )
        for index in order[:remainder]:
            extra[index] += 1
        return [1 + value for value in extra]

    def _normalize_draft_budgets(
        self,
        drafts: list[dict[str, Any]],
        *,
        child_kind: str,
        novel: Novel,
        parent: OutlineNode | None,
        siblings: list[OutlineNode],
    ) -> None:
        if child_kind not in {"volume", "arc"} or not drafts:
            return
        existing_budget = self._effective_existing_budget(siblings, child_kind)
        if child_kind == "volume":
            target = max(len(drafts), novel.planned_chapters - existing_budget)
        else:
            parent_budget = self._planned_chapters(parent.details if parent else None)
            target = max(
                len(drafts),
                (parent_budget or novel.planned_chapters) - existing_budget,
            )
        weights = [
            self._planned_chapters(
                draft.get("details") if isinstance(draft.get("details"), dict) else None
            )
            for draft in drafts
        ]
        for draft, budget in zip(drafts, self._allocate_budget(target, weights), strict=True):
            details = dict(draft.get("details") or {})
            details["planned_chapters"] = budget
            draft["details"] = details

    @staticmethod
    def _attach_pacing(drafts: list[dict[str, Any]], pacing: dict[str, Any]) -> None:
        plan = pacing.get("nodes") if isinstance(pacing.get("nodes"), list) else []
        for index, draft in enumerate(drafts):
            if index >= len(plan) or not isinstance(plan[index], dict):
                continue
            details = dict(draft.get("details") or {})
            details["pacing"] = dict(plan[index])
            draft["details"] = details

    def _generation_context(self, novel_id: str) -> dict[str, Any]:
        characters = self.session.scalars(
            select(StoryEntity)
            .where(
                StoryEntity.novel_id == novel_id,
                StoryEntity.entity_type == "character",
            )
            .order_by(StoryEntity.name)
            .limit(20)
        ).all()
        locations = self.session.scalars(
            select(StoryEntity)
            .where(
                StoryEntity.novel_id == novel_id,
                StoryEntity.entity_type == "location",
            )
            .order_by(StoryEntity.name)
            .limit(20)
        ).all()
        rules = self.session.scalars(
            select(NovelRule).where(NovelRule.novel_id == novel_id).limit(15)
        ).all()
        chapters = self.session.scalars(
            select(Chapter)
            .where(Chapter.novel_id == novel_id)
            .order_by(Chapter.chapter_index.desc())
            .limit(12)
        ).all()
        # chronological for prompt
        chapters = list(reversed(list(chapters)))

        blueprint = None
        try:
            from .services_blueprint import BlueprintService

            blueprint = BlueprintService(self.session).get_blueprint(novel_id)
        except Exception:
            blueprint = None

        return {
            "blueprint": blueprint,
            "characters": [
                {"name": c.name, "summary": c.summary or ""} for c in characters
            ],
            "locations": [
                {"name": location.name, "summary": location.summary or ""}
                for location in locations
            ],
            "rules": [r.rule for r in rules if r.rule],
            "prior_chapter_briefs": [
                {
                    "title": ch.title,
                    "goal": (ch.brief or {}).get("goal") or "",
                    "hook": (ch.brief or {}).get("hook") or "",
                }
                for ch in chapters
            ],
            "unresolved_foreshadow": self._unresolved_foreshadow(novel_id),
        }

    def _outline_context(
        self,
        *,
        novel_id: str,
        parent: OutlineNode | None,
        child_kind: str,
        siblings: list[OutlineNode],
        draft_count: int,
        chapter_offset: int = 0,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Add only the hierarchy state required by the next planning step."""
        if child_kind not in {"arc", "chapter", "scene"}:
            return context

        volume_plan = self._volume_plan_for_parent(novel_id, parent)
        arc_plan = self._arc_plan_for_parent(parent)
        enriched = {
            **context,
            "volume_plan": volume_plan,
            "arc_plan": arc_plan,
        }
        if child_kind == "chapter":
            existing_chapter_count = sum(
                1 for item in siblings if item.kind == "chapter"
            )
            enriched["pacing"] = self._pacing_for(
                  volume_plan=volume_plan,
                  arc_plan=arc_plan,
                  existing_chapter_count=existing_chapter_count + max(0, chapter_offset),
                  batch_total=draft_count,
            )
        return enriched

    def _unresolved_foreshadow(self, novel_id: str) -> list[str]:
        """Collect planted-but-not-yet-paid-off foreshadowing across the outline."""
        nodes = self.session.scalars(
            select(OutlineNode).where(OutlineNode.novel_id == novel_id)
        ).all()
        planted: list[str] = []
        paid: set[str] = set()
        for node in nodes:
            details = node.details or {}
            for item in details.get("foreshadow_plant") or []:
                text = str(item).strip()
                if text:
                    planted.append(text)
            for item in details.get("foreshadow_payoff") or []:
                text = str(item).strip()
                if text:
                    paid.add(text)

        def _norm(s: str) -> str:
            return "".join(ch for ch in s if ch.isalnum())

        paid_norm = {_norm(p) for p in paid}
        unresolved: list[str] = []
        seen: set[str] = set()
        for text in planted:
            key = _norm(text)
            if not key or key in seen:
                continue
            # Treat as resolved if a payoff shares a significant substring.
            if any(key in pn or pn in key for pn in paid_norm if len(pn) >= 4):
                continue
            seen.add(key)
            unresolved.append(text)
        return unresolved[:20]

    def _volume_plan_for_parent(
        self, novel_id: str, parent: OutlineNode | None
    ) -> dict[str, Any]:
        """Find the volume ancestor of `parent` and return its plan details."""
        node = parent
        guard = 0
        while node is not None and guard < 10:
            guard += 1
            if node.kind == "volume":
                details = dict(node.details or {})
                details["title"] = node.title
                return details
            if not node.parent_id:
                break
            node = self.session.get(OutlineNode, node.parent_id)
        return {}

    def _arc_plan_for_parent(self, parent: OutlineNode | None) -> dict[str, Any]:
        """Find the arc ancestor of `parent` and return the structural brief."""
        node = parent
        guard = 0
        while node is not None and guard < 10:
            guard += 1
            if node.kind == "arc":
                details = dict(node.details or {})
                details["title"] = node.title
                return details
            if not node.parent_id:
                break
            node = self.session.get(OutlineNode, node.parent_id)
        return {}

    def _pacing_for(
        self,
        *,
        volume_plan: dict[str, Any],
        arc_plan: dict[str, Any],
        existing_chapter_count: int,
        batch_total: int,
    ) -> dict[str, Any]:
        """Create one explicit pacing instruction per generated chapter.

        The arc budget has priority because a chapter needs a local dramatic
        function. The volume budget remains present for the model as the larger
        stage constraint.
        """
        arc_total = self._planned_chapters(arc_plan)
        volume_total = self._planned_chapters(volume_plan)
        fallback_total = min(12, volume_total) if volume_total else 12
        total = max(arc_total, existing_chapter_count + batch_total, fallback_total, 1)
        nodes: list[dict[str, Any]] = []
        for batch_index in range(batch_total):
            position = existing_chapter_count + batch_index + 1
            fraction = min(1.0, position / total)
            phase = _phase_for(position, total)
            turn_index = min(
                3,
                int(fraction * 4),
            )
            key_turns = volume_plan.get("key_turns") or []
            target_turn = (
                str(key_turns[turn_index]).strip()
                if isinstance(key_turns, list) and turn_index < len(key_turns)
                else ""
            )
            nodes.append(
                {
                    "index": batch_index + 1,
                    "arcPosition": position,
                    "arcTotal": total,
                    "volumeTotal": volume_total or total,
                    "fraction": round(fraction, 3),
                    "phase": phase,
                    "phaseLabel": _PHASE_LABELS[phase],
                    "targetTurn": target_turn,
                }
            )
        return {
            "arcTotal": total,
            "volumeTotal": volume_total or total,
            "nodes": nodes,
        }

    def _run_coherence(
        self,
        *,
        novel_id: str,
        nodes: list[dict[str, Any]],
        existing_titles: list[str],
        prior_briefs: list[dict[str, Any]],
        volume_plan: dict[str, Any] | None = None,
        unresolved_foreshadow: list[str] | None = None,
        child_kind: str = "",
    ) -> dict[str, Any]:
        from .agents.skills_runtime import SkillRuntime, ensure_default_skills

        try:
            ensure_default_skills(self.session)
            result = SkillRuntime(self.session, novel_id=novel_id).invoke(
                skill_name="outline-coherence",
                agent_name="Outline",
                payload={
                    "nodes": nodes,
                    "existing_titles": existing_titles,
                    "prior_chapter_briefs": prior_briefs,
                    "volume_plan": volume_plan or {},
                    "unresolved_foreshadow": unresolved_foreshadow or [],
                    "child_kind": child_kind,
                },
            )
            if isinstance(result, dict):
                return result
        except Exception:
            pass
        return {"ok": True, "issue_count": 0, "issues": [], "score": 100, "pass": True}

    def _draft_nodes(
        self,
        *,
        novel_id: str,
        novel_payload: dict[str, Any],
        parent_payload: dict[str, Any] | None,
        child_kind: str,
        count: int,
        existing_titles: list[str],
        start_chapter_index: int,
        context: dict[str, Any] | None = None,
        mode: str = "children",
    ) -> tuple[list[dict[str, Any]], str, bool]:
        """Return nodes from a connected cloud model."""
        from .agents.skills_runtime import SkillRuntime, ensure_default_skills

        context = context or {}
        # Prefer SkillRuntime so generation is permissioned + logged.
        try:
            ensure_default_skills(self.session)
            skill_result = SkillRuntime(self.session, novel_id=novel_id).invoke(
                skill_name="outline-generate",
                agent_name="Outline",
                payload={
                    "child_kind": child_kind,
                    "count": count,
                    "novel": novel_payload,
                    "parent": parent_payload,
                    "existing_titles": existing_titles,
                    "start_chapter_index": start_chapter_index,
                    "characters": context.get("characters") or [],
                    "locations": context.get("locations") or [],
                    "rules": context.get("rules") or [],
                    "prior_chapter_briefs": context.get("prior_chapter_briefs") or [],
                    "blueprint": context.get("blueprint"),
                    "volume_plan": context.get("volume_plan") or {},
                    "arc_plan": context.get("arc_plan") or {},
                    "pacing": context.get("pacing") or {},
                    "unresolved_foreshadow": context.get("unresolved_foreshadow") or [],
                    "mode": mode,
                },
            )
            if skill_result.get("ok") and skill_result.get("nodes"):
                source = str(skill_result.get("source") or "skill")
                if source != "model":
                    source = "skill"
                return (
                    list(skill_result["nodes"]),
                    source,
                    False,
                )
        except Exception:
            pass

        # Direct model path remains available if the skill registry is unavailable.
        config = model_config_for_role(self.session, novel_id, "大纲")
        if config is None:
            config = model_config_for_role(self.session, novel_id, "写作")
        if config is None:
            raise ValueError("请先连接可用的云端模型，再生成大纲。")
        try:
            nodes = AgentScopeOutlineAgent(config).generate_children(
                    novel=novel_payload,
                    parent=parent_payload,
                    child_kind=child_kind,
                    count=count,
                    existing_titles=existing_titles,
                    start_chapter_index=start_chapter_index,
                    characters=context.get("characters") or [],
                    locations=context.get("locations") or [],
                    rules=context.get("rules") or [],
                    prior_chapter_briefs=context.get("prior_chapter_briefs") or [],
                    mode=mode,
                    blueprint=context.get("blueprint") or {},
                    volume_plan=context.get("volume_plan") or {},
                    arc_plan=context.get("arc_plan") or {},
                    pacing=context.get("pacing") or {},
                    unresolved_foreshadow=context.get("unresolved_foreshadow") or [],
                )
        except Exception as exc:
            raise ValueError("云端模型未能生成大纲，请检查连接后重试。") from exc
        if not nodes:
            raise ValueError("云端模型没有返回可用的大纲，请重试。")
        return nodes, "model", False
