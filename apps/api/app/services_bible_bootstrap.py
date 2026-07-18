"""Parallel story-bible generation used by the one-idea bootstrap flow."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .agents.bible_bootstrap import (
    AgentScopeCharacterBibleAgent,
    AgentScopeWorldBibleAgent,
    CharacterBibleDraft,
    WorldBibleDraft,
)
from .agents.models import model_config_for_role
from .craft import CKSKILL_RULESET_VERSION, normalize_writing_profile
from .db import SessionLocal
from .models import Novel, NovelRule, StoryEntity, new_id


class BibleBootstrapService:
    def __init__(
        self,
        session: Session,
        *,
        session_factory: Callable[[], Session] = SessionLocal,
    ):
        self.session = session
        self.session_factory = session_factory

    def build(
        self, novel: Novel, *, blueprint: dict[str, Any]
    ) -> dict[str, Any]:
        novel_payload = {
            "title": novel.title,
            "genre": novel.genre,
            "coreIdea": novel.core_idea,
            "style": novel.style,
            "narrativePov": novel.narrative_pov,
            "plannedChapters": novel.planned_chapters,
            "targetWords": novel.target_words,
            "writingProfile": normalize_writing_profile(novel.writing_profile),
        }
        with ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="novel-bible-bootstrap",
        ) as pool:
            character_future = pool.submit(
                self._draft_characters,
                novel.id,
                novel_payload,
                blueprint,
            )
            world_future = pool.submit(
                self._draft_world,
                novel.id,
                novel_payload,
                blueprint,
            )
            characters, character_source = character_future.result()
            world, world_source = world_future.result()

        for item in characters["characters"]:
            self._upsert_entity(
                novel,
                entity_type="character",
                name=item["name"],
                summary=item["summary"],
                data={
                    "role": item["role"],
                    "status": item["status"],
                    "goal": item["goal"],
                    "flaw": item["flaw"],
                    "voice": item["voice"],
                    "relationship_to_protagonist": item[
                        "relationship_to_protagonist"
                    ],
                },
            )
        for item in world["locations"]:
            self._upsert_entity(
                novel,
                entity_type="location",
                name=item["name"],
                summary=item["summary"],
                data={
                    "region": item["region"],
                    "state": item["state"],
                    "depth": item["depth"],
                },
            )
        for item in world["factions"]:
            self._upsert_entity(
                novel,
                entity_type="faction",
                name=item["name"],
                summary=item["summary"],
                data={
                    "kind": item["kind"],
                    "stance": item["stance"],
                    "power": item["power"],
                },
            )
        for item in world["rules"]:
            self._upsert_rule(
                novel,
                rule=item["rule"],
                rule_type=item["type"],
                importance=item["importance"],
            )
        self.session.commit()
        counts = self.counts(novel.id)
        return {
            "counts": counts,
            "draftSources": {
                "characters": character_source,
                "world": world_source,
            },
            "source": "auto_bootstrap",
            "ruleset": CKSKILL_RULESET_VERSION,
        }

    def counts(self, novel_id: str) -> dict[str, int]:
        entities = self.session.scalars(
            select(StoryEntity).where(StoryEntity.novel_id == novel_id)
        ).all()
        return {
            "characters": sum(item.entity_type == "character" for item in entities),
            "locations": sum(item.entity_type == "location" for item in entities),
            "factions": sum(item.entity_type == "faction" for item in entities),
            "rules": len(
                self.session.scalars(
                    select(NovelRule).where(NovelRule.novel_id == novel_id)
                ).all()
            ),
        }

    def _draft_characters(
        self,
        novel_id: str,
        novel_payload: dict[str, Any],
        blueprint: dict[str, Any],
    ) -> tuple[CharacterBibleDraft, str]:
        with self.session_factory() as worker_session:
            config = self._model_config(worker_session, novel_id)
            if config is None:
                raise ValueError("请先连接可用的云端模型，再生成人物设定。")
            try:
                draft = AgentScopeCharacterBibleAgent(config).generate(
                    novel=novel_payload,
                    blueprint=blueprint,
                )
            except Exception as exc:
                raise ValueError("云端模型未能生成人物设定，请检查连接后重试。") from exc
            if len(draft["characters"]) < 4:
                raise ValueError("云端模型返回的人物设定不完整，请重试。")
            return draft, "model"

    def _draft_world(
        self,
        novel_id: str,
        novel_payload: dict[str, Any],
        blueprint: dict[str, Any],
    ) -> tuple[WorldBibleDraft, str]:
        with self.session_factory() as worker_session:
            config = self._model_config(worker_session, novel_id)
            if config is None:
                raise ValueError("请先连接可用的云端模型，再生成世界设定。")
            try:
                draft = AgentScopeWorldBibleAgent(config).generate(
                    novel=novel_payload,
                    blueprint=blueprint,
                )
            except Exception as exc:
                raise ValueError("云端模型未能生成世界设定，请检查连接后重试。") from exc
            if (
                len(draft["locations"]) < 3
                or len(draft["factions"]) < 2
                or len(draft["rules"]) < 2
            ):
                raise ValueError("云端模型返回的世界设定不完整，请重试。")
            return draft, "model"

    @staticmethod
    def _model_config(session: Session, novel_id: str):
        try:
            config = model_config_for_role(session, novel_id, "大纲")
            if config is None:
                config = model_config_for_role(session, novel_id, "写作")
            return config
        except Exception:
            return None

    def _upsert_entity(
        self,
        novel: Novel,
        *,
        entity_type: str,
        name: str,
        summary: str,
        data: dict[str, Any],
    ) -> StoryEntity:
        entity = self.session.scalar(
            select(StoryEntity).where(
                StoryEntity.novel_id == novel.id,
                StoryEntity.entity_type == entity_type,
                StoryEntity.name == name,
            )
        )
        metadata = {
            "source": "auto_bootstrap",
            "ruleset_version": CKSKILL_RULESET_VERSION,
        }
        if entity is None:
            entity = StoryEntity(
                id=new_id(),
                workspace_id=novel.workspace_id,
                novel_id=novel.id,
                entity_type=entity_type,
                name=name,
                summary=summary,
                data={**data, **metadata},
                locked_fields=[],
            )
            self.session.add(entity)
            return entity

        locked = set(entity.locked_fields or [])
        if "summary" not in locked and summary:
            entity.summary = summary
        merged = dict(entity.data or {})
        for key, value in data.items():
            if key in locked or f"data.{key}" in locked:
                continue
            merged[key] = value
        merged.update(metadata)
        entity.data = merged
        return entity

    def _upsert_rule(
        self,
        novel: Novel,
        *,
        rule: str,
        rule_type: str,
        importance: str,
    ) -> NovelRule:
        existing = self.session.scalar(
            select(NovelRule).where(
                NovelRule.novel_id == novel.id,
                NovelRule.rule == rule,
            )
        )
        if existing is not None:
            if not existing.locked:
                existing.rule_type = rule_type
                existing.importance = importance
            return existing
        created = NovelRule(
            id=new_id(),
            workspace_id=novel.workspace_id,
            novel_id=novel.id,
            rule=rule,
            rule_type=rule_type,
            importance=importance,
            locked=False,
            violations=0,
        )
        self.session.add(created)
        return created
