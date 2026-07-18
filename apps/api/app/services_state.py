from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import (
    Chapter,
    CharacterState,
    LocationState,
    StoryEntity,
    new_id,
)


def character_state_dict(state: CharacterState, name: str = "") -> dict[str, Any]:
    return {
        "id": state.id,
        "entityId": state.entity_id,
        "name": name,
        "chapterId": state.chapter_id,
        "chapterIndex": state.chapter_index,
        "location": state.location,
        "bodyStatus": state.body_status,
        "alive": state.alive,
        "emotion": state.emotion,
        "knownFacts": state.known_facts or [],
        "beliefs": state.beliefs or [],
        "inventory": state.inventory or [],
        "notes": state.notes,
    }


def location_state_dict(state: LocationState, name: str = "") -> dict[str, Any]:
    return {
        "id": state.id,
        "entityId": state.entity_id,
        "name": name,
        "chapterId": state.chapter_id,
        "chapterIndex": state.chapter_index,
        "condition": state.condition,
        "controlledBy": state.controlled_by,
        "notes": state.notes,
    }


class StateService:
    def __init__(self, session: Session):
        self.session = session

    def latest_character_states(self, novel_id: str, before_index: int | None = None) -> list[dict[str, Any]]:
        entities = {
            e.id: e
            for e in self.session.scalars(
                select(StoryEntity).where(
                    StoryEntity.novel_id == novel_id,
                    StoryEntity.entity_type == "character",
                )
            ).all()
        }
        states = self.session.scalars(
            select(CharacterState)
            .where(CharacterState.novel_id == novel_id)
            .order_by(CharacterState.chapter_index.desc())
        ).all()
        latest: dict[str, CharacterState] = {}
        for state in states:
            if before_index is not None and state.chapter_index >= before_index:
                continue
            if state.entity_id not in latest:
                latest[state.entity_id] = state
        return [
            character_state_dict(state, entities[eid].name if eid in entities else "")
            for eid, state in latest.items()
        ]

    def latest_location_states(self, novel_id: str, before_index: int | None = None) -> list[dict[str, Any]]:
        entities = {
            e.id: e
            for e in self.session.scalars(
                select(StoryEntity).where(
                    StoryEntity.novel_id == novel_id,
                    StoryEntity.entity_type == "location",
                )
            ).all()
        }
        states = self.session.scalars(
            select(LocationState)
            .where(LocationState.novel_id == novel_id)
            .order_by(LocationState.chapter_index.desc())
        ).all()
        latest: dict[str, LocationState] = {}
        for state in states:
            if before_index is not None and state.chapter_index >= before_index:
                continue
            if state.entity_id not in latest:
                latest[state.entity_id] = state
        return [
            location_state_dict(state, entities[eid].name if eid in entities else "")
            for eid, state in latest.items()
        ]

    def list_character_history(self, entity_id: str) -> list[dict[str, Any]]:
        entity = self.session.get(StoryEntity, entity_id)
        name = entity.name if entity else ""
        states = self.session.scalars(
            select(CharacterState)
            .where(CharacterState.entity_id == entity_id)
            .order_by(CharacterState.chapter_index)
        ).all()
        return [character_state_dict(s, name) for s in states]

    def apply_from_memory_delta(self, chapter: Chapter, delta: dict[str, Any]) -> dict[str, int]:
        """Write chapter-scoped states from memory extraction candidates."""
        entities = {
            item.name: item
            for item in self.session.scalars(
                select(StoryEntity).where(StoryEntity.novel_id == chapter.novel_id)
            ).all()
        }
        character_states = {
            state.entity_id: state
            for state in self.session.scalars(
                select(CharacterState).where(CharacterState.chapter_id == chapter.id)
            ).all()
        }
        location_states = {
            state.entity_id: state
            for state in self.session.scalars(
                select(LocationState).where(LocationState.chapter_id == chapter.id)
            ).all()
        }
        touched_character_ids: set[str] = set()
        touched_location_ids: set[str] = set()

        for item in delta.get("entity_updates") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            entity = entities.get(name)
            if entity is None:
                continue
            facts = item.get("facts") if isinstance(item.get("facts"), dict) else {}
            if entity.entity_type == "character":
                self._upsert_character_state(
                    chapter, entity, facts, item, character_states
                )
                touched_character_ids.add(entity.id)
            elif entity.entity_type == "location":
                self._upsert_location_state(
                    chapter, entity, facts, item, location_states
                )
                touched_location_ids.add(entity.id)

        # Infer crude character presence from events.
        for event in delta.get("events") or []:
            if not isinstance(event, dict):
                continue
            location = str(event.get("location") or "")
            for subject in event.get("subjects") or []:
                entity = entities.get(str(subject))
                if entity is None or entity.entity_type != "character":
                    continue
                existing = character_states.get(entity.id)
                if existing is None:
                    existing = CharacterState(
                        id=new_id(),
                        workspace_id=chapter.workspace_id,
                        novel_id=chapter.novel_id,
                        entity_id=entity.id,
                        chapter_id=chapter.id,
                        chapter_index=chapter.chapter_index,
                        location=location,
                        notes=str(event.get("action") or "")[:200],
                    )
                    self.session.add(existing)
                    character_states[entity.id] = existing
                elif location and not existing.location:
                    existing.location = location
                touched_character_ids.add(entity.id)

        self.session.commit()
        return {
            "characterStates": len(touched_character_ids),
            "locationStates": len(touched_location_ids),
        }

    def _upsert_character_state(
        self,
        chapter: Chapter,
        entity: StoryEntity,
        facts: dict[str, Any],
        item: dict[str, Any],
        states: dict[str, CharacterState],
    ) -> None:
        state = states.get(entity.id)
        if state is None:
            state = CharacterState(
                id=new_id(),
                workspace_id=chapter.workspace_id,
                novel_id=chapter.novel_id,
                entity_id=entity.id,
                chapter_id=chapter.id,
                chapter_index=chapter.chapter_index,
            )
            self.session.add(state)
            states[entity.id] = state

        if "location" in facts:
            state.location = str(facts.get("location") or "")
        if "body_status" in facts or "bodyStatus" in facts:
            state.body_status = str(facts.get("body_status") or facts.get("bodyStatus") or state.body_status)
        if "alive" in facts:
            state.alive = bool(facts.get("alive"))
        if "emotion" in facts:
            state.emotion = str(facts.get("emotion") or "")
        if "known_facts" in facts or "knownFacts" in facts:
            raw = facts.get("known_facts") or facts.get("knownFacts") or []
            state.known_facts = [str(x) for x in raw] if isinstance(raw, list) else state.known_facts
        if "beliefs" in facts:
            raw = facts.get("beliefs") or []
            state.beliefs = [str(x) for x in raw] if isinstance(raw, list) else state.beliefs
        if "inventory" in facts:
            raw = facts.get("inventory") or []
            state.inventory = [str(x) for x in raw] if isinstance(raw, list) else state.inventory
        if item.get("summary"):
            state.notes = str(item.get("summary") or state.notes)

    def _upsert_location_state(
        self,
        chapter: Chapter,
        entity: StoryEntity,
        facts: dict[str, Any],
        item: dict[str, Any],
        states: dict[str, LocationState],
    ) -> None:
        state = states.get(entity.id)
        if state is None:
            state = LocationState(
                id=new_id(),
                workspace_id=chapter.workspace_id,
                novel_id=chapter.novel_id,
                entity_id=entity.id,
                chapter_id=chapter.id,
                chapter_index=chapter.chapter_index,
            )
            self.session.add(state)
            states[entity.id] = state
        condition = str(facts.get("condition") or facts.get("status") or state.condition or "normal")
        if condition not in {"normal", "destroyed", "blocked", "occupied"}:
            condition = "normal"
        state.condition = condition
        state.controlled_by = str(facts.get("controlled_by") or facts.get("controlledBy") or "")
        if item.get("summary"):
            state.notes = str(item.get("summary") or "")

    def continuity_issues_from_states(
        self, *, novel_id: str, chapter_index: int, content: str
    ) -> list[dict[str, Any]]:
        """Rule checks against latest structured states entering this chapter."""
        issues: list[dict[str, Any]] = []
        characters = self.latest_character_states(novel_id, before_index=chapter_index)
        locations = self.latest_location_states(novel_id, before_index=chapter_index)

        for char in characters:
            name = char.get("name") or ""
            if not name:
                continue
            if not char.get("alive") and name in content:
                # Allow if content explains resurrection — still flag as fatal candidate.
                if "复活" not in content and "假死" not in content and "误传" not in content:
                    issues.append(
                        {
                            "severity": "fatal",
                            "type": "人物生死",
                            "evidence": name,
                            "reason": (
                                f"「{name}」进入本章前状态为死亡，正文却出现且无解释；"
                                f"来源章节 {char.get('chapterId')}（第 {char.get('chapterIndex')} 章）"
                            ),
                            "sourceChapterId": char.get("chapterId"),
                        }
                    )
            known = char.get("knownFacts") or []
            # If text claims they always knew something not in known_facts and uses leak phrase nearby.
            if "早就知道" in content and name in content:
                issues.append(
                    {
                        "severity": "fatal",
                        "type": "知识边界",
                        "evidence": f"{name}…早就知道",
                        "reason": (
                            f"「{name}」可能泄漏未知信息（已知事实 {len(known)} 条）；"
                            f"来源章节 {char.get('chapterId')}（第 {char.get('chapterIndex')} 章）"
                        ),
                        "sourceChapterId": char.get("chapterId"),
                    }
                )

        for loc in locations:
            name = loc.get("name") or ""
            condition = loc.get("condition") or "normal"
            if not name or name not in content:
                continue
            if condition == "destroyed" and "重建" not in content and "修复" not in content:
                issues.append(
                    {
                        "severity": "fatal",
                        "type": "地点状态",
                        "evidence": name,
                        "reason": (
                            f"「{name}」此前为毁坏，正文中出现且无解释恢复；"
                            f"来源章节 {loc.get('chapterId')}（第 {loc.get('chapterIndex')} 章）"
                        ),
                        "sourceChapterId": loc.get("chapterId"),
                    }
                )
            if condition == "blocked" and "封锁" not in content and "突破" not in content:
                issues.append(
                    {
                        "severity": "major",
                        "type": "地点状态",
                        "evidence": name,
                        "reason": f"「{name}」此前封锁，正文使用时未交代通行条件",
                    }
                )
        return issues
