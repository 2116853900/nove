"""Story blueprint (top-level story bible) storage + generation.

The blueprint is the book's structural backbone: logline, protagonist arc,
core conflict, world核心, and the网文 satisfaction loop. It is generated once
(preview→commit) and then injected as standing context into every downstream
outline generation so volumes/chapters stay consistent with the premise.

Stored as a single StoryEntity(entity_type="blueprint") row — no schema change.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .agents.blueprint import (
    AgentScopeBlueprintAgent,
    normalize_blueprint,
    suggested_volume_count,
)
from .agents.models import model_config_for_role
from .memory.outline_preview_store import get_preview, pop_preview, put_preview
from .models import Novel, StoryEntity, new_id
from .craft import normalize_writing_profile, profile_readiness

BLUEPRINT_ENTITY_TYPE = "blueprint"
BLUEPRINT_ENTITY_NAME = "__story_blueprint__"


class BlueprintService:
    def __init__(self, session: Session):
        self.session = session

    def _row(self, novel_id: str) -> StoryEntity | None:
        return self.session.scalar(
            select(StoryEntity).where(
                StoryEntity.novel_id == novel_id,
                StoryEntity.entity_type == BLUEPRINT_ENTITY_TYPE,
            )
        )

    def get_blueprint(self, novel_id: str) -> dict[str, Any] | None:
        row = self._row(novel_id)
        if row is None:
            return None
        return normalize_blueprint(row.data or {})

    def _novel_payload(self, novel: Novel) -> dict[str, Any]:
        return {
            "title": novel.title,
            "genre": novel.genre,
            "coreIdea": novel.core_idea,
            "style": novel.style,
            "narrativePov": novel.narrative_pov,
            "plannedChapters": novel.planned_chapters,
            "targetWords": novel.target_words,
            "writingProfile": normalize_writing_profile(novel.writing_profile),
        }

    def _draft(self, novel: Novel) -> tuple[dict[str, Any], str]:
        """Return a cloud-model blueprint or fail without creating a draft."""
        payload = self._novel_payload(novel)
        volume_hint = suggested_volume_count(novel.planned_chapters)
        config = None
        try:
            config = model_config_for_role(self.session, novel.id, "大纲")
            if config is None:
                config = model_config_for_role(self.session, novel.id, "写作")
        except Exception:
            config = None
        if config is None or str(getattr(config, "status", "") or "") != "connected":
            raise ValueError("请先连接可用的云端模型，再搭建故事。")
        try:
            data = AgentScopeBlueprintAgent(config).generate(
                novel=payload, volume_hint=volume_hint
            )
        except Exception as exc:
            raise ValueError("云端模型未能生成故事方向，请检查连接后重试。") from exc
        if not (data.get("logline") or data.get("protagonist", {}).get("goal")):
            raise ValueError("云端模型没有返回可用的故事方向，请重试。")
        return data, "model"

    def preview(self, novel: Novel) -> dict[str, Any]:
        blueprint, source = self._draft(novel)
        preview = put_preview(
            self.session,
            novel_id=novel.id,
            parent_id=None,
            child_kind=BLUEPRINT_ENTITY_TYPE,
            create_chapters=False,
            nodes=[{"kind": BLUEPRINT_ENTITY_TYPE, "title": "故事蓝图", "details": blueprint}],
            source=source,
            mode="blueprint",
        )
        return {
            "previewId": preview["previewId"],
            "draftSource": source,
            "blueprint": blueprint,
            "expiresAt": preview["expiresAt"],
        }

    def commit(
        self,
        novel: Novel,
        *,
        preview_id: str | None = None,
        blueprint: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Persist the blueprint. Accepts an edited blueprint or a preview id."""
        data: dict[str, Any] | None = None
        source = "user"
        if preview_id:
            record = get_preview(self.session, preview_id, novel_id=novel.id)
            if record is None:
                raise ValueError("preview not found or expired")
            nodes = record.get("nodes") or []
            if nodes and isinstance(nodes[0], dict):
                data = nodes[0].get("details") or {}
            source = str(record.get("source") or "user")
        if blueprint is not None:
            # Explicit edited blueprint overrides preview draft.
            data = blueprint
            source = "user"
        if data is None:
            raise ValueError("no blueprint to commit")

        normalized = normalize_blueprint(data)
        if not normalized.get("book_title"):
            normalized["book_title"] = novel.title.strip()
        if not normalized.get("genre"):
            normalized["genre"] = novel.genre.strip()
        if not normalized.get("book_title") or normalized["book_title"] in {
            "未命名小说",
            "未命名",
            "Untitled",
        } or not normalized.get("genre") or normalized["genre"] in {"未分类", "让 AI 判断"}:
            raise ValueError("故事方向缺少书名或题材，请让云端模型重新生成。")
        self._apply_to_novel(novel, normalized)
        row = self._row(novel.id)
        if row is None:
            row = StoryEntity(
                id=new_id(),
                workspace_id=novel.workspace_id,
                novel_id=novel.id,
                entity_type=BLUEPRINT_ENTITY_TYPE,
                name=BLUEPRINT_ENTITY_NAME,
                summary=normalized.get("logline") or "",
                data=normalized,
                locked_fields=[],
            )
            self.session.add(row)
        else:
            row.summary = normalized.get("logline") or ""
            row.data = normalized
        self.session.commit()
        if preview_id:
            pop_preview(self.session, preview_id, novel_id=novel.id)
        return {
            "blueprint": normalized,
            "draftSource": source,
            "previewId": preview_id,
        }

    def _apply_to_novel(self, novel: Novel, blueprint: dict[str, Any]) -> None:
        """Fill missing creation-profile fields without replacing author choices."""
        generated_genre = str(blueprint.get("genre") or "").strip()
        if generated_genre and novel.genre.strip() in {"", "未分类", "让 AI 判断"}:
            novel.genre = generated_genre[:80]
        profile = normalize_writing_profile(novel.writing_profile)
        protagonist = blueprint.get("protagonist") or {}
        world = blueprint.get("world") or {}
        reader = blueprint.get("reader_contract") or {}
        constraints = blueprint.get("creative_constraints") or {}

        suggestions = {
            "target_audience": reader.get("target_audience") or f"喜欢{novel.genre}强情节故事的读者",
            "platform": reader.get("platform") or "番茄小说",
            "protagonist_name": protagonist.get("name") or "林川",
            "protagonist_desire": protagonist.get("goal") or blueprint.get("core_conflict") or novel.core_idea,
            "protagonist_flaw": protagonist.get("flaw_or_start") or "起点资源不足，错误选择会造成可见后果",
            "world_scale": world.get("setting") or f"{novel.genre}故事世界",
            "power_system": world.get("power_system") or "能力成长遵循由低到高的清晰阶梯",
            "golden_finger": protagonist.get("golden_finger") or "可成长但受资源限制的独特能力",
            "golden_finger_cost": protagonist.get("golden_finger_cost") or "每次突破都消耗稀缺资源并带来可见风险",
            "antagonist_mirror": constraints.get("antagonist_mirror") or blueprint.get("antagonist") or "对立面以相反方法追求相似目标",
            "anti_trope": constraints.get("anti_trope") or "避免无代价胜利和重复打脸",
        }
        for key, value in suggestions.items():
            if not profile.get(key) and str(value or "").strip():
                profile[key] = str(value).strip()

        hard_constraints = list(profile.get("hard_constraints") or [])
        candidates = list(constraints.get("hard_constraints") or []) + list(world.get("rules") or [])
        candidates.extend(
            [
                "关键胜利必须由已展示的能力、选择或资源促成",
                "每卷结束必须改变主角的处境、关系或目标",
            ]
        )
        for item in candidates:
            text = str(item or "").strip()
            if text and text not in hard_constraints:
                hard_constraints.append(text)
            if len(hard_constraints) >= 2:
                break
        profile["hard_constraints"] = hard_constraints[:12]
        profile["auto_generated"] = True
        profile["strict_workflow"] = False
        profile = normalize_writing_profile(profile)
        if profile_readiness(profile)["ready"]:
            profile["strict_workflow"] = True
        novel.writing_profile = profile

        generated_title = str(blueprint.get("book_title") or "").strip()
        if generated_title and novel.title.strip() in {"未命名小说", "未命名", "Untitled"}:
            novel.title = generated_title[:200]
