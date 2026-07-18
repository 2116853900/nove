from __future__ import annotations

import random
import shutil
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from src.core.config import Config
from src.core.path_provider import PathProvider
from src.core.session_store import MarkdownSessionStore
from src.web.manifest.compat import normalized_parts, relative_candidates, relative_to_run_dir
import src.web.chat.event_signals as _event_signals
from src.web.chat.io_utils import read_json, write_json
import src.web.chat.memory_summary as _memory_summary
import src.web.chat.persona_context as _persona_context
import src.web.chat.relation_excerpt as _relation_excerpt
import src.web.chat.prompt_rules as _prompt_rules
import src.web.chat.relation_state as _relation_state
import src.web.chat.runtime_overview as _runtime_overview
import src.web.chat.scene_signals as _scene_signals
import src.web.chat.state_utils as _state_utils
import src.web.chat.text_utils as _text_utils
from src.web.artifacts.ingest import load_relations_source
from src.web.time_utils import utc_now as _utc_now


class DialogueService:
    SESSION_STATE_VERSION = 1

    def __init__(
        self,
        runs_root: str | Path,
        *,
        memory_store_resolver: Callable[[str], MarkdownSessionStore] | None = None,
    ) -> None:
        self.runs_root = Path(runs_root)
        self._memory_store_resolver = memory_store_resolver
        self._memory_stores: dict[str, MarkdownSessionStore] = {}

    @classmethod
    def _empty_session_state(cls) -> dict[str, Any]:
        return _state_utils.empty_session_state(cls.SESSION_STATE_VERSION)

    def _ensure_session_state(self, session: dict[str, Any]) -> dict[str, Any]:
        return _state_utils.ensure_session_state(session, version=self.SESSION_STATE_VERSION)

    def _session_scene_progress(self, session: dict[str, Any]) -> dict[str, Any]:
        state = self._ensure_session_state(session)
        return _state_utils.session_scene_progress(state)

    def _set_session_scene_progress(self, session: dict[str, Any], scene_progress: dict[str, Any] | None) -> None:
        state = self._ensure_session_state(session)
        payload = dict(scene_progress or {})
        updated_at = str(payload.get("updated_at", "")).strip() or _utc_now()
        _state_utils.set_session_scene_progress(state, payload, updated_at=updated_at)
        self._sync_character_runtime_cards(session, payload, updated_at=updated_at)

    def _session_relation_matrix(self, session: dict[str, Any]) -> dict[str, Any]:
        state = self._ensure_session_state(session)
        return _state_utils.relation_matrix(state)

    def _set_session_relation_matrix(self, session: dict[str, Any], payload: dict[str, Any] | None) -> None:
        state = self._ensure_session_state(session)
        _state_utils.set_relation_matrix(state, payload)

    def _session_relation_delta(self, session: dict[str, Any]) -> dict[str, Any]:
        state = self._ensure_session_state(session)
        return _state_utils.relation_delta(state)

    def _set_session_relation_delta(self, session: dict[str, Any], payload: dict[str, Any] | None) -> None:
        state = self._ensure_session_state(session)
        _state_utils.set_relation_delta(state, payload)

    def _session_character_snapshots(self, session: dict[str, Any]) -> dict[str, Any]:
        state = self._ensure_session_state(session)
        return _state_utils.character_snapshots(state)

    def _set_session_character_snapshots(self, session: dict[str, Any], payload: dict[str, Any] | None) -> None:
        state = self._ensure_session_state(session)
        _state_utils.set_character_snapshots(state, payload)

    def _sync_character_runtime_cards(
        self,
        session: dict[str, Any],
        scene_progress: dict[str, Any] | None,
        *,
        updated_at: str,
    ) -> None:
        state = self._ensure_session_state(session)
        snapshots = dict(state.get("characters", {}).get("snapshots", {}) or {})
        progress = dict(scene_progress or {})
        participants = [str(item).strip() for item in list(session.get("participants", []) or []) if str(item).strip()]
        present = {
            str(item).strip()
            for item in list(progress.get("present_participants", []) or [])
            if str(item).strip()
        }
        location = str(progress.get("location", "")).strip()
        time_hint = str(progress.get("time_hint", "")).strip()
        for name in participants:
            current = dict(snapshots.get(name, {}) or {})
            current["present_state"] = "onstage" if name in present else "offstage"
            if location:
                current["scene_location"] = location
            if time_hint:
                current["time_hint"] = time_hint
            current["updated_at"] = updated_at
            snapshots[name] = current
        state.setdefault("characters", {})["snapshots"] = snapshots

    def _session_event_signals(self, session: dict[str, Any]) -> dict[str, Any]:
        state = self._ensure_session_state(session)
        return _state_utils.event_signals(state)

    def _set_session_event_signals(self, session: dict[str, Any], payload: dict[str, Any] | None) -> None:
        state = self._ensure_session_state(session)
        _state_utils.set_event_signals(state, payload)

    def _session_memory_summary_state(self, session: dict[str, Any]) -> dict[str, Any]:
        state = self._ensure_session_state(session)
        return _state_utils.memory_summary(state)

    def _set_session_memory_summary_state(self, session: dict[str, Any], payload: dict[str, Any] | None) -> None:
        state = self._ensure_session_state(session)
        _state_utils.set_memory_summary(state, payload)

    def list_sessions(self, run_id: str) -> list[dict[str, Any]]:
        root = self._sessions_root(run_id)
        items: list[dict[str, Any]] = []
        if not root.exists():
            return items
        for path in sorted(root.glob("*/session.json"), reverse=True):
            payload = self._read_json(path)
            items.append(self._serialize_session(run_id, payload))
        items.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
        return items

    def create_session(
        self,
        run_manifest: dict[str, Any],
        *,
        mode: str,
        participants: list[str],
        controlled_character: str = "",
        scene_profile: dict[str, str] | None = None,
        self_profile: dict[str, str] | None = None,
        carried_memory_summary: dict[str, str] | None = None,
        branch_origin: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = str(run_manifest.get("run_id", "")).strip()
        novel_id = str(run_manifest.get("novel_id", "")).strip()
        available = self._character_index(run_manifest)
        available_names = [item["name"] for item in available]
        selected = [name for name in participants if name in available_names]
        if not selected:
            selected = available_names
        if not selected:
            raise ValueError("No persona bundles available for dialogue.")
        if mode not in {"act", "insert", "observe"}:
            raise ValueError("Unsupported dialogue mode.")
        if mode == "act" and controlled_character not in selected:
            raise ValueError("Controlled character must be one of the selected participants.")

        session_id = f"dlg-{uuid4().hex[:10]}"
        root = self._session_dir(run_id, session_id)
        root.mkdir(parents=True, exist_ok=True)
        payload = {
            "kind": "zaomeng_dialogue_session",
            "session_id": session_id,
            "run_id": run_id,
            "novel_id": novel_id,
            "mode": mode,
            "participants": selected,
            "controlled_character": controlled_character if mode == "act" else "",
            "scene_card": dict(scene_profile or {}),
            "scene_card_id": str((scene_profile or {}).get("scene_card_id", "")).strip(),
            "scene_history": [],
            "self_insert": dict(self_profile or {}) if mode == "insert" else {},
            "self_card_id": str((self_profile or {}).get("self_card_id", "")).strip() if mode == "insert" else "",
            "carried_memory_summary": dict(carried_memory_summary or {}),
            "branch_origin": dict(branch_origin or {}),
            "history": [],
            "pending_turn": {},
            "state": self._empty_session_state(),
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "status": "ready",
        }
        self._set_session_relation_matrix(payload, self._seed_relation_matrix(run_manifest, selected))
        if dict(scene_profile or {}):
            initial_summary = self._build_session_memory_summary(run_id, payload, [])
            payload["scene_history"] = [
                self._build_scene_history_entry(
                    scene_profile or {},
                    transition_message="",
                    memory_summary=initial_summary,
                )
            ]
        self._set_session_scene_progress(payload, self._derive_scene_progress_state(payload, []))
        self._write_json(root / "session.json", payload)
        if carried_memory_summary:
            session_store = self._resolve_memory_store(run_id)
            if session_store is not None:
                session_store.append_long_term_memory(
                    session_id,
                    _memory_summary.branch_memory_seed_text(carried_memory_summary),
                    metadata={
                        "run_id": run_id,
                        "kind": "branch_summary",
                        "speaker": "分支摘要",
                        "target": "",
                        "ts": _utc_now(),
                    },
                )
        return self._serialize_session(run_id, payload)

    def get_session(self, run_id: str, session_id: str) -> dict[str, Any]:
        payload = self._read_json(self._session_file(run_id, session_id))
        return self._serialize_session(run_id, payload)

    def delete_session(self, run_id: str, session_id: str) -> None:
        session_dir = self._session_dir(run_id, session_id)
        if not session_dir.exists():
            raise FileNotFoundError(str(session_dir))
        shutil.rmtree(session_dir)

    def update_scene_card(
        self,
        run_id: str,
        session_id: str,
        *,
        scene_profile: dict[str, str] | None = None,
        transition_message: str = "",
    ) -> dict[str, Any]:
        session = self._read_json(self._session_file(run_id, session_id))
        if session.get("pending_turn"):
            raise ValueError("当前还有一轮待收口，请先等这拍结束再转场。")
        normalized_scene = dict(scene_profile or {})
        session["scene_card"] = normalized_scene
        session["scene_card_id"] = str(normalized_scene.get("scene_card_id", "")).strip()
        scene_note = self._build_scene_switch_note(normalized_scene, transition_message)
        if scene_note:
            session.setdefault("history", []).append(
                {
                    "speaker": "场景提示",
                    "message": scene_note,
                    "target": "",
                    "ts": _utc_now(),
                }
            )
        self._set_session_scene_progress(session, self._derive_scene_progress_state(session, self._serialize_transcript(session)))
        transcript = self._serialize_transcript(session)
        memory_summary = self._build_session_memory_summary(run_id, session, transcript)
        scene_history = list(session.get("scene_history", []) or [])
        scene_history.append(
            self._build_scene_history_entry(
                normalized_scene,
                transition_message=transition_message,
                memory_summary=memory_summary,
            )
        )
        session["scene_history"] = scene_history
        session["updated_at"] = _utc_now()
        session["status"] = "ready"
        self._write_json(self._session_file(run_id, session_id), session)
        return self._serialize_session(run_id, session)

    def update_scene_progress_state(
        self,
        run_id: str,
        session_id: str,
        scene_progress: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self._read_json(self._session_file(run_id, session_id))
        self._set_session_scene_progress(
            session,
            self._merge_scene_progress_state(
                session,
                dict(scene_progress or {}),
            ),
        )
        session["updated_at"] = _utc_now()
        self._write_json(self._session_file(run_id, session_id), session)
        return self._serialize_session(run_id, session)

    def branch_session_from_scene(
        self,
        run_manifest: dict[str, Any],
        session_id: str,
        *,
        scene_index: int,
    ) -> dict[str, Any]:
        run_id = str(run_manifest.get("run_id", "")).strip()
        session = self._read_json(self._session_file(run_id, session_id))
        scene_history = list(session.get("scene_history", []) or [])
        if scene_index < 0 or scene_index >= len(scene_history):
            raise ValueError("指定的场景时间线节点不存在。")
        target = dict(scene_history[scene_index] or {})
        scene_profile = dict(target.get("scene_card", {}) or {})
        if not scene_profile:
            scene_profile = {
                "scene_card_id": str(target.get("scene_card_id", "")).strip(),
                "title": str(target.get("title", "")).strip(),
                "location": str(target.get("location", "")).strip(),
                "atmosphere": str(target.get("atmosphere", "")).strip(),
            }
        memory_summary = dict(target.get("memory_summary", {}) or {})
        return self.create_session(
            run_manifest,
            mode=str(session.get("mode", "observe")).strip() or "observe",
            participants=list(session.get("participants", []) or []),
            controlled_character=str(session.get("controlled_character", "")).strip(),
            scene_profile=scene_profile,
            self_profile=dict(session.get("self_insert", {}) or {}),
            carried_memory_summary=memory_summary,
            branch_origin={
                "session_id": str(session.get("session_id", "")).strip(),
                "scene_index": scene_index,
                "scene_title": str(target.get("title", "")).strip(),
            },
        )

    def prepare_turn(
        self,
        run_manifest: dict[str, Any],
        *,
        session_id: str,
        message: str,
        message_kind: str = "dialogue",
        speaker_override: str = "",
        transcript_message: str | None = None,
    ) -> dict[str, Any]:
        run_id = str(run_manifest.get("run_id", "")).strip()
        session = self._read_json(self._session_file(run_id, session_id))
        normalized_message_kind = self._normalize_message_kind(message_kind)
        effective_speaker_override = str(speaker_override or "").strip()
        if normalized_message_kind == "narration" and not effective_speaker_override:
            effective_speaker_override = "场景提示"
        turn_id = f"turn-{uuid4().hex[:8]}"
        payload = self._build_turn_payload(
            run_manifest,
            session,
            turn_id=turn_id,
            message=message,
            speaker_override=effective_speaker_override,
            message_kind=normalized_message_kind,
        )
        turn_dir = self._session_dir(run_id, session_id) / "turns"
        turn_dir.mkdir(parents=True, exist_ok=True)
        turn_payload_path = turn_dir / f"{turn_id}.payload.json"
        self._write_json(turn_payload_path, payload)
        session["pending_turn"] = {
            "turn_id": turn_id,
            "user_message": message,
            "transcript_message": message if transcript_message is None else transcript_message,
            "message_kind": normalized_message_kind,
            "speaker": payload["input"]["speaker"],
            "mode": payload["mode"],
            "participants": list(payload["input"]["participants"]),
            "active_participants": list(payload["input"].get("active_participants", [])),
            "response_limit_hint": payload["host_action"]["response_limit_hint"],
            "payload_path": str(turn_payload_path.resolve()),
            "created_at": _utc_now(),
        }
        session["updated_at"] = _utc_now()
        session["status"] = "waiting_for_host_reply"
        self._write_json(self._session_file(run_id, session_id), session)
        return self._serialize_session(run_id, session)

    def build_suggestion_payload(
        self,
        run_manifest: dict[str, Any],
        *,
        session_id: str,
        seed_text: str = "",
    ) -> dict[str, Any]:
        run_id = str(run_manifest.get("run_id", "")).strip()
        session = self._read_json(self._session_file(run_id, session_id))
        payload = self._build_turn_payload(
            run_manifest,
            session,
            turn_id=f"suggest-{uuid4().hex[:8]}",
            message=seed_text,
        )
        mode = str(payload.get("mode", "observe")).strip() or "observe"
        speaker = str(payload.get("input", {}).get("speaker", "")).strip()
        participants = list(payload.get("input", {}).get("participants", []))
        payload["kind"] = "zaomeng_dialogue_suggestion"
        scene_progress = dict(payload.get("scene_progress", {}) or {})
        session_summary = dict(dict(payload.get("memory_context", {}) or {}).get("session_summary", {}) or {})
        payload["user_persona"] = self._build_user_suggestion_persona(
            mode,
            session,
            payload.get("persona_contexts", []),
            scene_progress=scene_progress,
            session_summary=session_summary,
        )
        payload["instructions"] = {
            "mode": mode,
            "generation_goal": "Draft one short, natural, directly sendable next user line that fits the current scene, relationships, and persona voices.",
            "mode_rule": self._suggestion_mode_rule(mode),
            "speaker_rule": self._speaker_rule(mode, session),
            "response_style": self._suggestion_style_rule(mode),
        }
        payload["host_action"] = {
            "expected_output": {"suggestion": "一句可直接发送的话"},
            "output_rule": "Keep it short, in-scene, directly sendable, and never explanatory.",
        }
        payload["host_prompt_brief"] = self._host_suggestion_prompt_brief(
            mode,
            speaker,
            participants,
            scene_progress=scene_progress,
        )
        payload["updated_at"] = _utc_now()
        return payload

    def ingest_turn_responses(
        self,
        run_id: str,
        *,
        session_id: str,
        responses: list[dict[str, str]],
        remember_turn_memory: bool = False,
    ) -> dict[str, Any]:
        session = self._read_json(self._session_file(run_id, session_id))
        pending = dict(session.get("pending_turn", {}) or {})
        if not pending:
            raise ValueError("No pending turn to ingest.")
        session_store = self._resolve_memory_store(run_id) if remember_turn_memory else None
        clean_responses = []
        for item in responses:
            speaker = str(item.get("speaker", "")).strip()
            message = str(item.get("message", "")).strip()
            if not speaker or not message:
                continue
            clean_responses.append({"speaker": speaker, "message": message, "ts": _utc_now()})
        if not clean_responses:
            raise ValueError("No valid responses provided.")
        transcript_message = str(pending.get("transcript_message", pending.get("user_message", ""))).strip()
        if transcript_message:
            user_entry = {
                "speaker": pending.get("speaker", "User"),
                "message": transcript_message,
                "target": "",
                "ts": pending.get("created_at", _utc_now()),
            }
            if session_store is not None:
                session_store.append_long_term_memory(
                    session_id,
                    self._entry_to_memory_text(user_entry),
                    metadata={
                        "run_id": run_id,
                        "kind": self._normalize_message_kind(str(pending.get("message_kind", "")).strip()),
                        "speaker": str(user_entry.get("speaker", "")).strip(),
                        "target": "",
                        "ts": user_entry.get("ts", ""),
                    },
                )
                user_entry["memory_archived"] = True
            session.setdefault("history", []).append(user_entry)
        remembered_responses = []
        pending_speaker = str(pending.get("speaker", "")).strip()
        active_participants = [str(item).strip() for item in pending.get("active_participants", []) if str(item).strip()]
        session["history"].extend(clean_responses)
        for item in clean_responses:
            response_entry = item
            if session_store is not None:
                target = pending_speaker if pending_speaker not in {"", "User", "场景提示", "旁白"} else ""
                if not target:
                    pool = [name for name in active_participants if name and name != str(response_entry.get("speaker", "")).strip()]
                    target = pool[0] if pool else ""
                session_store.append_long_term_memory(
                    session_id,
                    self._entry_to_memory_text(response_entry),
                    metadata={
                        "run_id": run_id,
                        "kind": "dialogue",
                        "speaker": str(response_entry.get("speaker", "")).strip(),
                        "target": target,
                        "ts": response_entry.get("ts", ""),
                    },
                )
                response_entry["memory_archived"] = True
            remembered_responses.append(response_entry)
        if remembered_responses:
            session["history"][-len(remembered_responses) :] = remembered_responses
        session["pending_turn"] = {}
        session["updated_at"] = _utc_now()
        session["status"] = "ready"
        if session_store is not None:
            session_store.compress_context(session)
        result_path = self._session_dir(run_id, session_id) / "turns" / f"{pending.get('turn_id', 'turn')}.result.json"
        self._write_json(
            result_path,
            {
                "kind": "zaomeng_dialogue_result",
                "session_id": session_id,
                "turn_id": pending.get("turn_id", ""),
                "responses": clean_responses,
                "updated_at": _utc_now(),
            },
        )
        self._write_json(self._session_file(run_id, session_id), session)
        return self._serialize_session(run_id, session)

    def _build_turn_payload(
        self,
        run_manifest: dict[str, Any],
        session: dict[str, Any],
        *,
        turn_id: str,
        message: str,
        message_kind: str = "dialogue",
        speaker_override: str = "",
    ) -> dict[str, Any]:
        participants = list(session.get("participants", []))
        mode = str(session.get("mode", "observe")).strip() or "observe"
        normalized_message_kind = self._normalize_message_kind(message_kind)
        speaker = str(speaker_override or "").strip() or (
            session.get("controlled_character", "")
            if mode == "act"
            else session.get("self_insert", {}).get("display_name", "你")
            if mode == "insert"
            else "User"
        )
        character_index = self._character_index(run_manifest)
        persona_map = {item["name"]: item for item in character_index}
        relation_graph = dict(run_manifest.get("artifact_index", {}).get("relation_graph", {}) or {})
        full_history = list(session.get("history", []))
        scene_progress = self._session_scene_progress(session)
        character_snapshots = self._session_character_snapshots(session)
        active_participants = self._resolve_active_participants(participants, full_history, mode, speaker, scene_progress)
        scene_card = dict(session.get("scene_card", {}) or {})
        transcript = self._serialize_transcript(session)

        persona_contexts = self._build_persona_contexts(
            participants=participants,
            active_participants=active_participants,
            persona_map=persona_map,
            mode=mode,
            controlled_character=str(session.get("controlled_character", "")).strip(),
            character_snapshots=character_snapshots,
        )

        latest_history = full_history[-8:]
        relation_excerpt = self._build_relation_excerpt(
            relation_graph.get("relations_file", ""),
            participants=participants,
            active_participants=active_participants,
            message=message,
            scene_card=scene_card,
        )
        session_relation_excerpt = self._build_session_relation_excerpt(
            session,
            participants=participants,
            active_participants=active_participants,
        )
        if session_relation_excerpt:
            relation_excerpt = (
                f"{relation_excerpt}\n\n# SESSION_RELATION_STATE\n{session_relation_excerpt}".strip()
                if relation_excerpt
                else f"# SESSION_RELATION_STATE\n{session_relation_excerpt}"
            )
        memory_context = self._build_turn_memory_context(
            run_id=str(run_manifest.get("run_id", "")).strip(),
            session=session,
            transcript=transcript,
            speaker=speaker,
            message=message,
            participants=participants,
            active_participants=active_participants,
            scene_card=scene_card,
            scene_progress=scene_progress,
        )
        controlled_character_name = str(session.get("controlled_character", "")).strip()
        response_limit_hint = self._choose_response_limit_hint(
            mode=mode,
            active_count=len(active_participants),
            turn_id=turn_id,
            message_kind=normalized_message_kind,
        )
        response_count_rule = (
            f"Return 1-{response_limit_hint} in-world replies. "
            "Let only characters who are currently present respond; do not force every participant to speak each turn."
        )
        if normalized_message_kind == "narration" and mode == "act" and controlled_character_name:
            response_lower_bound = min(response_limit_hint, max(1, min(2, len(active_participants))))
            response_count_rule = (
                f"Return {response_lower_bound}-{response_limit_hint} in-world replies "
                f"when multiple cast members are present. Other participants besides {controlled_character_name} must speak; "
                "do not return only the controlled character's line."
            )
        instructions = {
            "mode": mode,
            "generation_goal": "Keep every reply faithful to the persona bundle, relationship context, and scene mode.",
            "mode_rule": self._mode_rule(mode, normalized_message_kind, controlled_character_name),
            "speaker_rule": self._speaker_rule(mode, session, normalized_message_kind),
            "response_style": self._response_style_rule(
                mode,
                normalized_message_kind,
                controlled_character_name,
            ),
            "scene_rule": self._scene_rule(scene_card),
            "progression_rule": self._scene_progress_rule(scene_progress),
            "response_count_rule": response_count_rule,
        }
        responder_hints = self._responder_hints(
            mode,
            active_participants,
            speaker,
            normalized_message_kind,
            controlled_character_name,
        )

        return {
            "kind": "zaomeng_dialogue_turn",
            "run_id": run_manifest.get("run_id", ""),
            "session_id": session.get("session_id", ""),
            "turn_id": turn_id,
            "novel_id": run_manifest.get("novel_id", ""),
            "mode": mode,
            "input": {
                "speaker": speaker,
                "message": message,
                "message_kind": normalized_message_kind,
                "participants": participants,
                "active_participants": active_participants,
                "controlled_character": session.get("controlled_character", ""),
                "scene_card": scene_card,
                "scene_progress": scene_progress,
                "character_snapshots": character_snapshots,
                "self_insert": dict(session.get("self_insert", {})),
            },
            "history": latest_history,
            "scene_card": scene_card,
            "memory_context": memory_context,
            "scene_progress": scene_progress,
            "persona_contexts": persona_contexts,
            "relation_context": {
                "graph": relation_graph,
                "relations_excerpt": relation_excerpt,
            },
            "instructions": instructions,
            "responder_hints": responder_hints,
            "host_action": {
                "expected_output": [
                    {"speaker": "CharacterName", "message": "..."}
                ],
                "response_limit_hint": response_limit_hint,
                "output_rule": (
                    "Return only in-world character replies. Do not explain the workflow or mention prompts. "
                    "Do not split obvious small actions into standalone narration; keep them inside the speaking character's line with brief parenthetical action."
                ),
            },
            "host_prompt_brief": self._host_prompt_brief(
                mode,
                speaker,
                participants,
                normalized_message_kind,
                controlled_character_name,
            ),
            "updated_at": _utc_now(),
        }

    _mode_rule = staticmethod(_prompt_rules._mode_rule)
    _speaker_rule = staticmethod(_prompt_rules._speaker_rule)
    _response_style_rule = staticmethod(_prompt_rules._response_style_rule)
    _scene_rule = staticmethod(_prompt_rules._scene_rule)
    _scene_progress_rule = staticmethod(_prompt_rules._scene_progress_rule)
    _suggestion_mode_rule = staticmethod(_prompt_rules._suggestion_mode_rule)
    _suggestion_style_rule = staticmethod(_prompt_rules._suggestion_style_rule)
    _build_user_suggestion_persona = staticmethod(_prompt_rules._build_user_suggestion_persona)
    _responder_hints = staticmethod(_prompt_rules._responder_hints)
    _host_prompt_brief = staticmethod(_prompt_rules._host_prompt_brief)
    _host_suggestion_prompt_brief = staticmethod(_prompt_rules._host_suggestion_prompt_brief)
    _normalize_message_kind = staticmethod(_prompt_rules._normalize_message_kind)

    @classmethod
    def _resolve_active_participants(
        cls,
        participants: list[str],
        history: list[dict[str, Any]],
        mode: str,
        speaker: str,
        scene_progress: dict[str, Any] | None = None,
    ) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for name in participants:
            normalized = str(name or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)
        if not deduped:
            return []

        state_present = [
            str(item).strip()
            for item in list(dict(scene_progress or {}).get("present_participants", []) or [])
            if str(item).strip() in deduped
        ]
        state_offstage = {
            str(item).strip()
            for item in list(dict(scene_progress or {}).get("offstage_participants", []) or [])
            if str(item).strip() in deduped
        }
        departed = _scene_signals.infer_departed_participants(deduped, history)
        if state_present:
            active = [name for name in state_present if name not in state_offstage and name not in departed]
            if mode == "act":
                active = [name for name in active if name != speaker]
            if active:
                return active

        active = [name for name in deduped if name not in departed]
        if mode == "act":
            active = [name for name in active if name != speaker]
        if active:
            return active
        # Never end up with an empty speaker pool.
        fallback = [name for name in deduped if not (mode == "act" and name == speaker)]
        return fallback or deduped[:1]

    def _merge_scene_progress_state(self, session: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
        base = self._derive_scene_progress_state(session, self._serialize_transcript(session))
        participants = [str(item).strip() for item in list(session.get("participants", []) or []) if str(item).strip()]
        allowed = set(participants)
        history = list(session.get("history", []) or [])

        def clean_names(values: Any) -> list[str]:
            names: list[str] = []
            for item in list(values or []):
                name = str(item or "").strip()
                if not name or name not in allowed or name in names:
                    continue
                names.append(name)
            return names

        present = clean_names(incoming.get("present_participants", [])) or list(base.get("present_participants", []) or [])
        offstage = [name for name in clean_names(incoming.get("offstage_participants", [])) if name not in present]
        present, offstage = self._stabilize_presence_transition(
            session,
            participants=participants,
            history=history,
            present=present,
            offstage=offstage,
            base=base,
        )
        merged = {
            "present_participants": present,
            "offstage_participants": offstage or [name for name in list(base.get("offstage_participants", []) or []) if name not in present],
            "time_hint": _scene_signals.merge_time_hint(
                incoming=str(incoming.get("time_hint", "")).strip(),
                base=str(base.get("time_hint", "")).strip(),
                history=history,
                scene_hint=str(dict(session.get("scene_card", {}) or {}).get("time_hint", "")).strip(),
                allow_history_drift=False,
            ),
            "location": str(incoming.get("location", "")).strip() or str(base.get("location", "")).strip(),
            "atmosphere_summary": str(incoming.get("atmosphere_summary", "")).strip() or str(base.get("atmosphere_summary", "")).strip(),
            "progression_note": str(incoming.get("progression_note", "")).strip() or str(base.get("progression_note", "")).strip(),
            "should_offer_scene_shift": bool(incoming.get("should_offer_scene_shift", base.get("should_offer_scene_shift", False))),
            "scene_shift_reason": str(incoming.get("scene_shift_reason", "")).strip() or str(base.get("scene_shift_reason", "")).strip(),
            "turns_in_current_scene": int(base.get("turns_in_current_scene", 0) or 0),
            "beat_maturity": int(incoming.get("beat_maturity", base.get("beat_maturity", 0)) or 0),
            "world_tension_summary": str(incoming.get("world_tension_summary", "")).strip() or str(base.get("world_tension_summary", "")).strip(),
            "updated_at": _utc_now(),
        }
        if merged["should_offer_scene_shift"]:
            merged["beat_maturity"] = max(75, int(merged.get("beat_maturity", 0) or 0))
        return merged

    def _derive_scene_progress_state(self, session: dict[str, Any], transcript: list[dict[str, Any]]) -> dict[str, Any]:
        participants = [str(item).strip() for item in list(session.get("participants", []) or []) if str(item).strip()]
        scene_card = dict(session.get("scene_card", {}) or {})
        prior = self._session_scene_progress(session)
        history = list(session.get("history", []) or [])
        presence_state = self._derive_presence_state(session, participants=participants, history=history)
        scene_frame = self._derive_scene_frame_state(session, transcript=transcript, scene_card=scene_card, prior=prior)
        progression_state = self._derive_progression_state(
            session,
            transcript=transcript,
            scene_card=scene_card,
            prior=prior,
            presence_state=presence_state,
            scene_frame=scene_frame,
        )
        progression_bits = []
        if scene_frame.get("location"):
            progression_bits.append(f"地点：{scene_frame['location']}")
        if scene_frame.get("time_hint"):
            progression_bits.append(f"时间：{scene_frame['time_hint']}")
        if scene_frame.get("atmosphere_summary"):
            progression_bits.append(f"氛围：{scene_frame['atmosphere_summary']}")
        if presence_state.get("present_participants"):
            progression_bits.append(f"在场：{'、'.join(list(presence_state.get('present_participants', []))[:4])}")
        if presence_state.get("offstage_participants"):
            progression_bits.append(f"离场：{'、'.join(list(presence_state.get('offstage_participants', []))[:3])}")
        progression_bits.append(f"成熟度：{int(progression_state.get('beat_maturity', 0) or 0)}")
        progression_note = "；".join(bit for bit in progression_bits if bit)
        return {
            **presence_state,
            **scene_frame,
            **progression_state,
            "progression_note": progression_note,
            "updated_at": _utc_now(),
        }

    def _derive_presence_state(
        self,
        session: dict[str, Any],
        *,
        participants: list[str],
        history: list[dict[str, Any]],
    ) -> dict[str, Any]:
        departed = _scene_signals.infer_departed_participants(participants, history)
        latest_exit = self._latest_event_signal(session, "cast_exit")
        latest_enter = self._latest_event_signal(session, "cast_enter")
        if latest_exit:
            actor = str(latest_exit.get("actor", "")).strip()
            if actor in participants:
                departed.add(actor)
        if latest_enter:
            actor = str(latest_enter.get("actor", "")).strip()
            if actor in participants:
                departed.discard(actor)
        present = [name for name in participants if name not in departed]
        if not present and participants:
            present = participants[:1]
        return {
            "present_participants": present,
            "offstage_participants": [name for name in participants if name not in present],
        }

    def _stabilize_presence_transition(
        self,
        session: dict[str, Any],
        *,
        participants: list[str],
        history: list[dict[str, Any]],
        present: list[str],
        offstage: list[str],
        base: dict[str, Any],
    ) -> tuple[list[str], list[str]]:
        prior_offstage = [str(item).strip() for item in list(base.get("offstage_participants", []) or []) if str(item).strip()]
        explicit_returns = _scene_signals.infer_returned_participants(participants, history)
        explicit_exits = _scene_signals.infer_departed_participants(participants, history)
        for event in list(self._session_event_signals(session).get("recent", []) or [])[-12:]:
            payload = dict(event or {})
            actor = str(payload.get("actor", "")).strip()
            kind = str(payload.get("kind", "")).strip()
            if actor not in participants:
                continue
            if kind == "cast_enter":
                explicit_returns.add(actor)
                explicit_exits.discard(actor)
            elif kind == "cast_exit":
                explicit_exits.add(actor)
                explicit_returns.discard(actor)

        stabilized_offstage = {name for name in offstage if name in participants}
        stabilized_present = [name for name in present if name in participants]
        for name in prior_offstage:
            if name in explicit_returns:
                continue
            stabilized_offstage.add(name)
            stabilized_present = [item for item in stabilized_present if item != name]
        for name in explicit_exits:
            stabilized_offstage.add(name)
            stabilized_present = [item for item in stabilized_present if item != name]

        ordered_present: list[str] = []
        for name in participants:
            if name in stabilized_present and name not in stabilized_offstage and name not in ordered_present:
                ordered_present.append(name)
        if not ordered_present:
            ordered_present = [name for name in participants if name not in stabilized_offstage][:1] or participants[:1]
        ordered_offstage = [name for name in participants if name in stabilized_offstage and name not in ordered_present]
        return ordered_present, ordered_offstage

    def _derive_scene_frame_state(
        self,
        session: dict[str, Any],
        *,
        transcript: list[dict[str, Any]],
        scene_card: dict[str, Any],
        prior: dict[str, Any],
    ) -> dict[str, Any]:
        latest_time_event = self._latest_event_signal(session, "time_change")
        latest_scene_event = self._latest_event_signal(session, "scene_transition")
        time_hint = _scene_signals.merge_time_hint(
            incoming=(
                str(latest_time_event.get("time_hint", "")).strip()
                or _scene_signals.infer_time_hint(transcript)
            ),
            base=str(prior.get("time_hint", "")).strip(),
            history=list(session.get("history", []) or []),
            scene_hint=str(scene_card.get("time_hint", "")).strip(),
        )
        location = (
            str(latest_scene_event.get("location_hint", "")).strip()
            or str(prior.get("location", "")).strip()
            or str(scene_card.get("location", "")).strip()
        )
        latest_atmosphere_event = self._latest_event_signal(session, "atmosphere_shift")
        atmosphere_summary = (
            self._trim_summary_text(str(latest_atmosphere_event.get("cue", "")).strip(), 80)
            or self._infer_atmosphere_summary(transcript)
            or self._trim_summary_text(str(prior.get("atmosphere_summary", "")).strip(), 80)
            or self._trim_summary_text(str(scene_card.get("atmosphere", "")).strip(), 80)
        )
        return {
            "time_hint": time_hint,
            "location": location,
            "atmosphere_summary": atmosphere_summary,
        }

    def _derive_progression_state(
        self,
        session: dict[str, Any],
        *,
        transcript: list[dict[str, Any]],
        scene_card: dict[str, Any],
        prior: dict[str, Any],
        presence_state: dict[str, Any],
        scene_frame: dict[str, Any],
    ) -> dict[str, Any]:
        latest_beat_event = self._latest_event_signal(session, "beat_complete")
        turns_in_current_scene = self._count_current_scene_turns(session)
        beat_maturity = self._estimate_scene_maturity(
            turns_in_current_scene=turns_in_current_scene,
            transcript=transcript,
            scene_card=scene_card,
            presence_state=presence_state,
            scene_frame=scene_frame,
            latest_beat_event=latest_beat_event,
            prior=prior,
        )
        scene_shift_reason = ""
        should_offer_scene_shift = False
        if scene_card and beat_maturity >= 72:
            should_offer_scene_shift = True
            scene_shift_reason = "这一幕已经接了好几拍，可以顺势换到下一幕。"
        if latest_beat_event:
            should_offer_scene_shift = True
            scene_shift_reason = str(latest_beat_event.get("cue", "")).strip() or scene_shift_reason
        initial_time = str(scene_card.get("time_hint", "")).strip()
        time_hint = str(scene_frame.get("time_hint", "")).strip()
        if time_hint and initial_time and time_hint != initial_time and beat_maturity >= 55:
            should_offer_scene_shift = True
            scene_shift_reason = scene_shift_reason or f"时间已经自然推到{time_hint}，适合顺势转下一拍。"
        event_pressure_reason = self._derive_transition_pressure_reason(
            session,
            presence_state=presence_state,
            scene_frame=scene_frame,
            scene_card=scene_card,
            prior=prior,
        )
        if event_pressure_reason and beat_maturity >= 42:
            should_offer_scene_shift = True
            scene_shift_reason = scene_shift_reason or event_pressure_reason
        return {
            "should_offer_scene_shift": should_offer_scene_shift,
            "scene_shift_reason": scene_shift_reason,
            "turns_in_current_scene": turns_in_current_scene,
            "beat_maturity": beat_maturity,
            "world_tension_summary": self._derive_world_tension_summary(session, transcript=transcript, scene_frame=scene_frame),
        }

    def _derive_transition_pressure_reason(
        self,
        session: dict[str, Any],
        *,
        presence_state: dict[str, Any],
        scene_frame: dict[str, Any],
        scene_card: dict[str, Any],
        prior: dict[str, Any],
    ) -> str:
        present = [str(item).strip() for item in list(presence_state.get("present_participants", []) or []) if str(item).strip()]
        offstage = [str(item).strip() for item in list(presence_state.get("offstage_participants", []) or []) if str(item).strip()]
        latest_exit = self._latest_event_signal(session, "cast_exit")
        actor = str(latest_exit.get("actor", "")).strip()
        if actor and actor in offstage:
            if len(present) <= 1 and present:
                return f"{actor}已经离场，场上只剩{present[0]}，适合顺势切到下一幕。"
            return f"{actor}已经离场，在场关系重新收束，适合顺势转下一拍。"

        latest_scene_event = self._latest_event_signal(session, "scene_transition")
        location = str(scene_frame.get("location", "")).strip()
        if latest_scene_event and location:
            prior_location = str(prior.get("location", "")).strip()
            scene_location = str(scene_card.get("location", "")).strip()
            if location != prior_location and location != scene_location:
                return f"地点已经转到{location}，适合顺势接下一幕。"
        return ""

    def _estimate_scene_maturity(
        self,
        *,
        turns_in_current_scene: int,
        transcript: list[dict[str, Any]],
        scene_card: dict[str, Any],
        presence_state: dict[str, Any],
        scene_frame: dict[str, Any],
        latest_beat_event: dict[str, Any],
        prior: dict[str, Any],
    ) -> int:
        score = min(60, max(0, turns_in_current_scene * 10))
        if latest_beat_event:
            score += 25
        if str(scene_frame.get("time_hint", "")).strip() and str(scene_frame.get("time_hint", "")).strip() != str(scene_card.get("time_hint", "")).strip():
            score += 10
        if str(scene_frame.get("location", "")).strip() and str(scene_frame.get("location", "")).strip() != str(scene_card.get("location", "")).strip():
            score += 10
        if list(presence_state.get("offstage_participants", []) or []):
            score += 6
        if str(scene_frame.get("atmosphere_summary", "")).strip():
            score += 4
        previous_maturity = int(prior.get("beat_maturity", 0) or 0)
        if previous_maturity:
            score = max(score, min(100, previous_maturity - 8))
        if len(transcript) >= 6:
            score += 6
        return max(0, min(100, score))

    def _infer_atmosphere_summary(self, transcript: list[dict[str, Any]]) -> str:
        recent_messages = [
            str(item.get("message", "")).strip()
            for item in list(transcript or [])[-8:]
            if str(item.get("message", "")).strip()
        ]
        if not recent_messages:
            return ""
        joined = " ".join(recent_messages)
        for token in _scene_signals.ATMOSPHERE_TOKENS:
            if token in joined:
                return self._trim_summary_text(token, 40)
        for message in reversed(recent_messages):
            trimmed = self._trim_summary_text(message, 40)
            if trimmed:
                return trimmed
        return ""

    def _derive_world_tension_summary(
        self,
        session: dict[str, Any],
        *,
        transcript: list[dict[str, Any]],
        scene_frame: dict[str, Any],
    ) -> str:
        latest_atmosphere_event = self._latest_event_signal(session, "atmosphere_shift")
        latest_relation_event = self._latest_event_signal(session, "relationship_shift")
        latest_scene_event = self._latest_event_signal(session, "scene_transition", "environment_change", "time_change")
        for candidate in (latest_atmosphere_event, latest_relation_event, latest_scene_event):
            cue = self._trim_summary_text(str((candidate or {}).get("cue", "")).strip(), 88)
            if cue:
                return cue
        relation_delta = self._session_relation_delta(session)
        if relation_delta:
            pair_key, delta = next(iter(relation_delta.items()))
            metrics: list[str] = []
            for field, label in (("trust", "信任"), ("affection", "好感"), ("hostility", "敌意"), ("ambiguity", "摇摆")):
                amount = int(dict(delta or {}).get(field, 0) or 0)
                if amount:
                    metrics.append(f"{label}{amount:+d}")
            if metrics:
                return self._trim_summary_text(f"{pair_key} 当前仍在变化：{'、'.join(metrics)}", 88)
        atmosphere = str(scene_frame.get("atmosphere_summary", "")).strip()
        if atmosphere:
            return self._trim_summary_text(f"这一拍的气氛是：{atmosphere}", 88)
        for item in reversed(list(transcript or [])[-8:]):
            role = str(item.get("role", "")).strip()
            message = self._trim_summary_text(str(item.get("message", "")).strip(), 88)
            if role in {"scene", "director"} and message:
                return message
        return ""

    @staticmethod
    def _count_current_scene_turns(session: dict[str, Any]) -> int:
        history = list(session.get("history", []) or [])
        scene_history = list(session.get("scene_history", []) or [])
        if not history:
            return 0
        latest_scene_ts = str((scene_history[-1] or {}).get("ts", "")).strip() if scene_history else ""
        if latest_scene_ts:
            return sum(1 for item in history if str(item.get("ts", "")).strip() >= latest_scene_ts and str(item.get("message", "")).strip())
        return len([item for item in history[-12:] if str(item.get("message", "")).strip()])

    @staticmethod
    def _choose_response_limit_hint(*, mode: str, active_count: int, turn_id: str, message_kind: str) -> int:
        if active_count <= 0:
            return 1
        seed = sum(ord(ch) for ch in str(turn_id or ""))
        rng = random.Random(seed)
        if mode == "observe":
            upper = min(4, max(2, active_count))
            lower = 3 if active_count >= 4 else 2
            if message_kind == "narration":
                upper = min(5, max(upper, 3))
                lower = min(upper, 2 if active_count <= 2 else 3)
            return rng.randint(lower, upper)
        if message_kind == "narration" and mode in {"act", "insert"}:
            upper = min(4, max(1, active_count))
            lower = 2 if active_count >= 2 else 1
            return rng.randint(lower, upper)
        upper = min(3, max(1, active_count))
        lower = 1 if active_count <= 1 else 2
        return rng.randint(lower, upper)

    @staticmethod
    def _load_text_excerpt(path_text: str, *, limit: int) -> str:
        return _relation_excerpt.load_text_excerpt(path_text, limit=limit)

    @staticmethod
    def _pair_key(left: str, right: str) -> str:
        return _relation_state.pair_key(left, right)

    @staticmethod
    def _default_relation_entry() -> dict[str, Any]:
        return _relation_state.default_relation_entry()

    @classmethod
    def _normalize_relation_entry(cls, raw: dict[str, Any] | None) -> dict[str, Any]:
        return _relation_state.normalize_relation_entry(raw)

    def _seed_relation_matrix(self, run_manifest: dict[str, Any], participants: list[str]) -> dict[str, Any]:
        relation_graph = dict(run_manifest.get("artifact_index", {}).get("relation_graph", {}) or {})
        relation_path = Path(str(relation_graph.get("relations_file", "")).strip())
        if not relation_path.exists():
            return {}
        try:
            payload = load_relations_source(relation_path)
        except Exception:
            return {}
        relations = dict(payload.get("relations", {}) or {})
        return _relation_state.seed_relation_matrix(relations, participants)

    def _merged_relation_matrix(self, session: dict[str, Any], participants: list[str]) -> dict[str, Any]:
        return _relation_state.merged_relation_matrix(
            self._session_relation_matrix(session),
            self._session_relation_delta(session),
            participants,
        )

    @staticmethod
    def _empty_event_signals_state() -> dict[str, Any]:
        return _state_utils.empty_event_signals_state()

    def _merge_event_signals_state(self, session: dict[str, Any], incoming: list[dict[str, Any]]) -> dict[str, Any]:
        return _event_signals.merge_event_signals_state(
            self._session_event_signals(session),
            incoming,
            participants=list(session.get("participants", []) or []),
            updated_at=_utc_now(),
        )

    def _latest_event_signal(self, session: dict[str, Any], *kinds: str) -> dict[str, Any]:
        return _event_signals.latest_event_signal(self._session_event_signals(session), *kinds)

    def _build_session_relation_excerpt(
        self,
        session: dict[str, Any],
        *,
        participants: list[str],
        active_participants: list[str],
    ) -> str:
        deltas = self._session_relation_delta(session)
        if not deltas:
            return ""
        merged = self._merged_relation_matrix(session, participants)
        focus_keys: list[str] = []
        focus_names = [str(item).strip() for item in [*active_participants, *participants] if str(item).strip()]
        for index, left in enumerate(focus_names):
            for right in focus_names[index + 1 :]:
                pair_key = self._pair_key(left, right)
                if pair_key and pair_key not in focus_keys:
                    focus_keys.append(pair_key)
        lines: list[str] = []
        for pair_key in focus_keys:
            delta = dict(deltas.get(pair_key, {}) or {})
            if not delta:
                continue
            relation = dict(merged.get(pair_key, {}) or {})
            metric_bits: list[str] = []
            for field, label in (("trust", "信任"), ("affection", "好感"), ("hostility", "敌意"), ("ambiguity", "暧昧/摇摆")):
                change = int(delta.get(field, 0) or 0)
                if change:
                    metric_bits.append(f"{label}{change:+d}")
            if not metric_bits:
                continue
            status_bits = [
                f"trust={int(relation.get('trust', 5) or 5)}",
                f"affection={int(relation.get('affection', 5) or 5)}",
                f"hostility={int(relation.get('hostility', 0) or 0)}",
                f"ambiguity={int(relation.get('ambiguity', 3) or 3)}",
            ]
            line = f"## {pair_key}\n- session_delta: {', '.join(metric_bits)}\n- merged_state: {', '.join(status_bits)}"
            last_event = str(delta.get("last_event", "")).strip()
            if last_event:
                line = f"{line}\n- last_event: {self._trim_summary_text(last_event, 120)}"
            last_actor = str(delta.get("last_actor", "")).strip()
            last_target = str(delta.get("last_target", "")).strip()
            if last_actor or last_target:
                line = f"{line}\n- drift: {self._trim_summary_text(' -> '.join([item for item in (last_actor, last_target) if item]), 80)}"
            lines.append(line)
            if len("\n".join(lines)) >= 1200:
                break
        return "\n".join(lines).strip()

    def _build_session_event_excerpt(self, session: dict[str, Any]) -> list[dict[str, Any]]:
        return _event_signals.build_session_event_excerpt(self._session_event_signals(session))

    def _build_persona_contexts(
        self,
        *,
        participants: list[str],
        active_participants: list[str],
        persona_map: dict[str, dict[str, Any]],
        mode: str,
        controlled_character: str,
        character_snapshots: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return _persona_context.build_persona_contexts(
            participants=participants,
            active_participants=active_participants,
            persona_map=persona_map,
            mode=mode,
            controlled_character=controlled_character,
            character_snapshots=character_snapshots,
        )

    @staticmethod
    def _load_persona_profile(meta: dict[str, Any]) -> tuple[dict[str, Any], Path]:
        return _persona_context.load_persona_profile(meta)

    @staticmethod
    def _persona_preview_payload(meta: dict[str, Any], normalized_profile: dict[str, Any]) -> dict[str, Any]:
        return _persona_context.persona_preview_payload(meta, normalized_profile)

    @staticmethod
    def _persona_profile_payload(normalized_profile: dict[str, Any], *, detailed: bool) -> dict[str, Any]:
        return _persona_context.persona_profile_payload(normalized_profile, detailed=detailed)

    @staticmethod
    def _persona_snapshot_payload(snapshot: dict[str, Any], *, detailed: bool) -> dict[str, Any]:
        return _persona_context.persona_snapshot_payload(snapshot, detailed=detailed)

    def _build_relation_excerpt(
        self,
        path_text: str,
        *,
        participants: list[str],
        active_participants: list[str],
        message: str,
        scene_card: dict[str, Any],
    ) -> str:
        return _relation_excerpt.build_relation_excerpt(
            path_text,
            participants=participants,
            active_participants=active_participants,
            message=message,
            scene_card=scene_card,
        )

    @staticmethod
    def _choose_relation_excerpt_limit(*, participants: list[str], active_participants: list[str]) -> int:
        return _relation_excerpt.choose_relation_excerpt_limit(
            participants=participants,
            active_participants=active_participants,
        )

    @staticmethod
    def _choose_relation_excerpt_scan_limit(*, participants: list[str], active_participants: list[str]) -> int:
        return _relation_excerpt.choose_relation_excerpt_scan_limit(
            participants=participants,
            active_participants=active_participants,
        )

    @staticmethod
    def _extract_relevant_relation_excerpt(text: str, focus_terms: list[str], limit: int) -> str:
        return _relation_excerpt.extract_relevant_relation_excerpt(text, focus_terms, limit)

    def _build_turn_memory_context(
        self,
        *,
        run_id: str,
        session: dict[str, Any],
        transcript: list[dict[str, Any]],
        speaker: str,
        message: str,
        participants: list[str],
        active_participants: list[str],
        scene_card: dict[str, Any],
        scene_progress: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        state_summary = self._session_memory_summary_state(session)
        archived_summary = {
            "summary": self._trim_summary_text(str(state_summary.get("summary", "")).strip(), 360),
            "key_points": [
                self._trim_summary_text(str(item).strip(), 120)
                for item in list(state_summary.get("key_points", []) or [])[:5]
                if str(item).strip()
            ],
            "compressed_turns": int(state_summary.get("compressed_turns", 0) or 0),
            "recent_turns_kept": int(state_summary.get("recent_turns_kept", 0) or 0),
        }
        archived_summary = {
            key: value
            for key, value in archived_summary.items()
            if value not in ("", [], 0)
        }
        normalized_progress = dict(scene_progress or {})
        progress_snapshot = {
            "time_hint": self._trim_summary_text(str(normalized_progress.get("time_hint", "")).strip(), 32),
            "location": self._trim_summary_text(str(normalized_progress.get("location", "")).strip(), 48),
            "progression_note": self._trim_summary_text(str(normalized_progress.get("progression_note", "")).strip(), 120),
            "present_participants": [
                str(item).strip()
                for item in list(normalized_progress.get("present_participants", []) or [])[:6]
                if str(item).strip()
            ],
            "offstage_participants": [
                str(item).strip()
                for item in list(normalized_progress.get("offstage_participants", []) or [])[:6]
                if str(item).strip()
            ],
            "should_offer_scene_shift": bool(normalized_progress.get("should_offer_scene_shift", False)),
            "scene_shift_reason": self._trim_summary_text(str(normalized_progress.get("scene_shift_reason", "")).strip(), 120),
            "world_tension_summary": self._trim_summary_text(str(normalized_progress.get("world_tension_summary", "")).strip(), 120),
        }
        progress_snapshot = {
            key: value
            for key, value in progress_snapshot.items()
            if value not in ("", [], False)
        }
        character_snapshots = {
            str(name).strip(): self._persona_snapshot_payload(dict(snapshot or {}), detailed=True)
            for name, snapshot in self._session_character_snapshots(session).items()
            if str(name).strip() and self._persona_snapshot_payload(dict(snapshot or {}), detailed=True)
        }
        relation_delta = {
            str(pair_key).strip(): {
                key: value
                for key, value in dict(delta or {}).items()
                if value not in ("", [], 0, None)
            }
            for pair_key, delta in self._session_relation_delta(session).items()
            if str(pair_key).strip()
        }
        relation_delta = {key: value for key, value in relation_delta.items() if value}
        event_signals = self._build_session_event_excerpt(session)
        session_summary = self._build_session_memory_summary(run_id, session, transcript)
        memory_hits = self._search_turn_memory_hits(
            run_id=run_id,
            session_id=str(session.get("session_id", "")).strip(),
            speaker=speaker,
            message=message,
            participants=participants,
            active_participants=active_participants,
            scene_card=scene_card,
            session_summary=session_summary,
            scene_progress=progress_snapshot,
        )
        return {
            "session_summary": session_summary,
            "archived_summary": archived_summary,
            "retrieved_memories": memory_hits,
            "scene_progress": progress_snapshot,
            "character_snapshots": character_snapshots,
            "relation_delta": relation_delta,
            "event_signals": event_signals,
        }

    def _search_turn_memory_hits(
        self,
        *,
        run_id: str,
        session_id: str,
        speaker: str,
        message: str,
        participants: list[str],
        active_participants: list[str],
        scene_card: dict[str, Any],
        session_summary: dict[str, Any],
        scene_progress: dict[str, Any],
    ) -> list[dict[str, Any]]:
        if not session_id:
            return []
        store = self._resolve_memory_store(run_id)
        if store is None:
            return []
        query_parts: list[str] = []
        for item in [speaker, *active_participants[:3], *participants[:2]]:
            normalized = str(item).strip()
            if normalized and normalized not in query_parts:
                query_parts.append(normalized)
        for item in (
            str(scene_card.get("title", "")).strip(),
            str(scene_card.get("location", "")).strip(),
            str(scene_card.get("scene_drive", "")).strip(),
            str(scene_card.get("public_goal", "")).strip(),
            str(scene_card.get("hidden_tension", "")).strip(),
            str(session_summary.get("current_goal", "")).strip(),
            str(session_summary.get("unresolved_threads", "")).strip(),
            str(session_summary.get("current_location", "")).strip(),
            str(session_summary.get("current_companions", "")).strip(),
            str(session_summary.get("pending_commitments", "")).strip(),
            str(scene_progress.get("scene_shift_reason", "")).strip(),
            str(scene_progress.get("world_tension_summary", "")).strip(),
        ):
            if item and item not in query_parts:
                query_parts.append(item)
        trimmed_message = self._trim_summary_text(message, 80)
        if trimmed_message:
            query_parts.append(trimmed_message)
        if not query_parts:
            return []
        try:
            hits = store.search_long_term_memory(session_id, " ".join(query_parts), top_k=3)
        except Exception:
            return []
        normalized_hits: list[dict[str, Any]] = []
        for item in hits:
            text = self._trim_summary_text(str((item or {}).get("text", "")).strip(), 140)
            if not text:
                continue
            normalized_hit = {
                "text": text,
                "score": round(float(item.get("score", 0.0) or 0.0), 4),
                "speaker": str(item.get("speaker", "")).strip(),
                "target": str(item.get("target", "")).strip(),
                "kind": str(item.get("kind", "")).strip(),
            }
            normalized_hits.append(
                {
                    key: value
                    for key, value in normalized_hit.items()
                    if value not in ("", 0.0)
                }
            )
        return normalized_hits

    @staticmethod
    def _character_index(run_manifest: dict[str, Any]) -> list[dict[str, Any]]:
        return list(run_manifest.get("artifact_index", {}).get("characters", []) or [])

    def _serialize_session(self, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        session = dict(payload)
        session["file_urls"] = self._build_file_urls(run_id, session)
        session["mode_display"] = self._mode_display(str(session.get("mode", "")).strip())
        transcript = self._serialize_transcript(session)
        session["transcript"] = transcript
        session["scene_progress"] = self._session_scene_progress(session)
        session["relation_delta"] = self._session_relation_delta(session)
        session["character_snapshots"] = self._session_character_snapshots(session)
        session["event_signals"] = self._session_event_signals(session)
        session["relation_matrix"] = self._merged_relation_matrix(session, list(session.get("participants", []) or []))
        session["last_entry_preview"] = self._build_last_entry_preview(session)
        session["session_card"] = self._build_session_card(session)
        session["scene_history"] = self._serialize_scene_history(session)
        session["branch_origin"] = dict(session.get("branch_origin", {}) or {})
        session["pending_turn_summary"] = self._build_pending_turn_summary(session)
        session["session_memory_summary"] = self._build_session_memory_summary(run_id, session, transcript)
        session["runtime_state_overview"] = self._build_runtime_state_overview(session)
        return session

    def _serialize_transcript(self, session: dict[str, Any]) -> list[dict[str, Any]]:
        controlled = str(session.get("controlled_character", "")).strip()
        self_insert_name = str(session.get("self_insert", {}).get("display_name", "")).strip()
        mode = str(session.get("mode", "observe")).strip() or "observe"
        items: list[dict[str, Any]] = []
        for entry in session.get("history", []):
            speaker = str(entry.get("speaker", "")).strip()
            role = "character"
            if speaker in {"旁白", "场景提示"}:
                role = "director" if mode == "observe" else "scene"
            elif mode == "act" and speaker == controlled:
                role = "user"
            elif mode == "insert" and speaker == self_insert_name:
                role = "user"
            elif mode == "observe" and speaker == "User":
                role = "director"
            items.append(
                {
                    "speaker": speaker,
                    "message": str(entry.get("message", "")).strip(),
                    "role": role,
                }
            )
        return items

    _mode_display = staticmethod(_text_utils.mode_display)

    def _build_session_card(self, session: dict[str, Any]) -> dict[str, Any]:
        mode = str(session.get("mode", "observe")).strip() or "observe"
        card = {
            "mode": mode,
            "mode_display": self._mode_display(mode),
            "participants": list(session.get("participants", [])),
            "controlled_character": str(session.get("controlled_character", "")).strip(),
            "scene_card_id": str(session.get("scene_card_id", "")).strip(),
            "scene_card": dict(session.get("scene_card", {})),
            "self_card_id": str(session.get("self_card_id", "")).strip(),
            "self_insert": dict(session.get("self_insert", {})),
        }
        return card

    def _serialize_scene_history(self, session: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        current_scene_id = str(session.get("scene_card_id", "")).strip()
        for entry in list(session.get("scene_history", []) or []):
            title = str(entry.get("title", "")).strip()
            location = str(entry.get("location", "")).strip()
            atmosphere = str(entry.get("atmosphere", "")).strip()
            transition_message = str(entry.get("transition_message", "")).strip()
            scene_card_id = str(entry.get("scene_card_id", "")).strip()
            items.append(
                {
                    "scene_card_id": scene_card_id,
                    "title": title,
                    "location": location,
                    "atmosphere": atmosphere,
                    "transition_message": transition_message,
                    "scene_card": dict(entry.get("scene_card", {}) or {}),
                    "memory_summary": dict(entry.get("memory_summary", {}) or {}),
                    "ts": str(entry.get("ts", "")).strip(),
                    "is_current": "true" if current_scene_id and scene_card_id == current_scene_id else "",
                }
            )
        return items

    @staticmethod
    def _build_scene_history_entry(
        scene_profile: dict[str, Any],
        *,
        transition_message: str = "",
        memory_summary: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        scene = dict(scene_profile or {})
        return {
            "scene_card_id": str(scene.get("scene_card_id", "")).strip(),
            "title": str(scene.get("title", "")).strip(),
            "location": str(scene.get("location", "")).strip(),
            "atmosphere": str(scene.get("atmosphere", "")).strip(),
            "transition_message": str(transition_message or "").strip(),
            "scene_card": dict(scene),
            "memory_summary": dict(memory_summary or {}),
            "ts": _utc_now(),
        }

    def _build_pending_turn_summary(self, session: dict[str, Any]) -> dict[str, Any]:
        pending = dict(session.get("pending_turn", {}) or {})
        if not pending:
            return {}
        return {
            "turn_id": str(pending.get("turn_id", "")).strip(),
            "speaker": str(pending.get("speaker", "")).strip(),
            "message": str(pending.get("user_message", "")).strip(),
            "message_kind": self._normalize_message_kind(str(pending.get("message_kind", "")).strip()),
            "mode": str(pending.get("mode", "")).strip(),
            "participants": list(pending.get("participants", [])),
            "active_participants": list(pending.get("active_participants", [])),
            "response_limit_hint": int(pending.get("response_limit_hint", 0) or 0),
        }

    def _build_runtime_state_overview(self, session: dict[str, Any]) -> dict[str, Any]:
        return _runtime_overview.build_runtime_state_overview(
            scene_progress=self._session_scene_progress(session),
            session_summary=dict(session.get("session_memory_summary", {}) or {}),
            character_snapshots=self._session_character_snapshots(session),
            relation_delta=self._session_relation_delta(session),
            event_signals=self._session_event_signals(session),
        )

    def _build_session_memory_summary(self, run_id: str, session: dict[str, Any], transcript: list[dict[str, Any]]) -> dict[str, str]:
        mode = str(session.get("mode", "observe")).strip() or "observe"
        mode_display = self._mode_display(mode)
        participants = [str(item).strip() for item in session.get("participants", []) if str(item).strip()]
        history = list(session.get("history", []) or [])
        scene_progress = self._session_scene_progress(session)
        present_participants = [
            str(item).strip()
            for item in list(scene_progress.get("present_participants", []) or [])
            if str(item).strip()
        ]
        offstage_participants = [
            str(item).strip()
            for item in list(scene_progress.get("offstage_participants", []) or [])
            if str(item).strip()
        ]
        time_hint = str(scene_progress.get("time_hint", "")).strip()
        progress_location = str(scene_progress.get("location", "")).strip()
        progression_note = str(scene_progress.get("progression_note", "")).strip()
        shift_reason = str(scene_progress.get("scene_shift_reason", "")).strip()

        cast_speakers: list[str] = []
        seen: set[str] = set()
        for item in transcript:
            if str(item.get("role", "")).strip() != "character":
                continue
            speaker = str(item.get("speaker", "")).strip()
            if not speaker or speaker in seen:
                continue
            seen.add(speaker)
            cast_speakers.append(speaker)

        last_messages: list[str] = []
        for item in history[-6:]:
            text = str(item.get("message", "")).strip()
            if not text:
                continue
            last_messages.append(self._trim_summary_text(text, 88))
        last_messages = last_messages[-3:]

        recap = "这局刚开场，回顾会在这里滚动更新。"
        if last_messages:
            recap = f"最近一拍：{' / '.join(last_messages)}"

        cast = "人物发言次序会在这里收住。"
        if present_participants:
            cast = f"当前主要在场：{'、'.join(present_participants[:5])}{'...' if len(present_participants) > 5 else ''}"
            if offstage_participants:
                cast = f"{cast}；暂时离场：{'、'.join(offstage_participants[:3])}"
        elif cast_speakers:
            suffix = "..." if len(cast_speakers) > 5 else ""
            cast = f"当前主要在场：{'、'.join(cast_speakers[:5])}{suffix}"
        elif participants:
            cast = f"本局参与角色：{'、'.join(participants[:5])}{'...' if len(participants) > 5 else ''}"

        if mode == "act":
            controlled = str(session.get("controlled_character", "")).strip() or "该角色"
            perspective = f"你正以「{controlled}」发言，其他人会按角色关系回应。"
        elif mode == "insert":
            self_insert = dict(session.get("self_insert", {}) or {})
            self_name = str(self_insert.get("display_name", "")).strip() or "你"
            identity = str(self_insert.get("scene_identity", "")).strip()
            perspective = f"你以「{self_name}」入场（{identity}）。" if identity else f"你以「{self_name}」入场，直接参与这幕。"
        else:
            perspective = "你在旁观推进模式里，主要作用是推动局势进入下一拍。"
        scene_card = dict(session.get("scene_card", {}) or {})
        if scene_card:
            location = str(scene_card.get("location", "")).strip()
            atmosphere = str(scene_card.get("atmosphere", "")).strip()
            title = str(scene_card.get("title", "")).strip()
            scene_bits = [bit for bit in (title, location, atmosphere) if bit]
            if scene_bits:
                perspective = f"{perspective} 当前挂载场景：{' / '.join(scene_bits)}。"
        if time_hint:
            perspective = f"{perspective} 当前时间已经推进到「{time_hint}」。"

        world = "当前局势里的动作与情绪线会在这里提醒你。"
        world_tension_summary = str(scene_progress.get("world_tension_summary", "")).strip()
        if world_tension_summary:
            world = self._trim_summary_text(world_tension_summary, 88)
        elif progression_note:
            world = self._trim_summary_text(progression_note, 88)
        for item in reversed(transcript):
            role = str(item.get("role", "")).strip()
            text = str(item.get("message", "")).strip()
            if not text:
                continue
            if role in {"scene", "director"}:
                world = self._trim_summary_text(text, 88)
                break
        if world == "当前局势里的动作与情绪线会在这里提醒你。":
            for item in reversed(transcript):
                role = str(item.get("role", "")).strip()
                text = str(item.get("message", "")).strip()
                if role == "character" and text:
                    world = f"人物最新情绪线：{self._trim_summary_text(text, 78)}"
                    break

        relation = "关系线还在铺，先让人物多接几拍。"
        recent_character_speakers: list[str] = []
        for item in transcript[-10:]:
            if str(item.get("role", "")).strip() != "character":
                continue
            speaker = str(item.get("speaker", "")).strip()
            if speaker:
                recent_character_speakers.append(speaker)
        if len(recent_character_speakers) >= 2:
            chain = " → ".join(recent_character_speakers[-4:])
            relation = f"最近接话链：{chain}"
        elif cast_speakers:
            relation = f"本局关键人物：{'、'.join(cast_speakers[:4])}"

        session_id = str(session.get("session_id", "")).strip()
        semantic_hint = ""
        if session_id and self._ensure_memory_store(run_id):
            try:
                hits = self._memory_stores[run_id].search_long_term_memory(session_id, "关系 冲突 目标", top_k=1)
            except Exception:
                hits = []
            if hits:
                semantic_hint = str((hits[0] or {}).get("text", "")).strip()
        if semantic_hint:
            relation = f"{relation} · 长期记忆：{self._trim_summary_text(semantic_hint, 68)}"
        relation_delta = self._session_relation_delta(session)
        if relation_delta:
            delta_bits: list[str] = []
            for pair_key, delta in list(relation_delta.items())[:3]:
                metric_bits = []
                for field, label in (("trust", "信任"), ("affection", "好感"), ("hostility", "敌意"), ("ambiguity", "摇摆")):
                    change = int(dict(delta or {}).get(field, 0) or 0)
                    if change:
                        metric_bits.append(f"{label}{change:+d}")
                if metric_bits:
                    delta_bits.append(f"{pair_key}({','.join(metric_bits)})")
            if delta_bits:
                relation = f"{relation} · 本局变化：{'；'.join(delta_bits)}"

        carried_summary = dict(session.get("carried_memory_summary", {}) or {})
        if carried_summary and not history:
            carried_recap = str(carried_summary.get("recap", "")).strip()
            carried_cast = str(carried_summary.get("cast", "")).strip()
            carried_relation = str(carried_summary.get("relation_drift", "") or carried_summary.get("relation", "")).strip()
            carried_world = str(carried_summary.get("world", "")).strip()
            if carried_recap:
                recap = f"承接旧线：{self._trim_summary_text(carried_recap, 88)}"
            if carried_cast:
                cast = self._trim_summary_text(carried_cast, 88)
            if carried_relation:
                relation = self._trim_summary_text(carried_relation, 88)
            if carried_world:
                world = self._trim_summary_text(carried_world, 88)

        scene_frame = "当前这幕的地点、气氛与推进方向会在这里提醒你。"
        scene_card = dict(session.get("scene_card", {}) or {})
        if scene_card:
            scene_bits = [
                str(scene_card.get("title", "")).strip(),
                progress_location or str(scene_card.get("location", "")).strip(),
                str(scene_card.get("atmosphere", "")).strip(),
            ]
            scene_bits = [bit for bit in scene_bits if bit]
            drive = self._trim_summary_text(
                str(scene_card.get("scene_drive", "")).strip() or str(scene_card.get("opening_situation", "")).strip(),
                72,
            )
            if scene_bits:
                scene_frame = f"挂载场景：{' / '.join(scene_bits)}"
                if drive:
                    scene_frame = f"{scene_frame} · {drive}"
            elif drive:
                scene_frame = drive
        if time_hint:
            scene_frame = f"{scene_frame} · 当前时间：{time_hint}"
        if shift_reason:
            scene_frame = f"{scene_frame} · 转场提示：{self._trim_summary_text(shift_reason, 48)}"

        recent_commitments = _memory_summary.recent_commitment_summary(history)
        recent_conflicts = _memory_summary.recent_conflict_summary(history)
        recent_actions = _memory_summary.recent_action_summary(history)
        major_beats = _memory_summary.major_beat_summary(
            session,
            transcript,
            event_signals=self._session_event_signals(session),
        )
        current_goal = _memory_summary.current_goal_summary(session, scene_progress=scene_progress)
        unresolved_threads = _memory_summary.unresolved_thread_summary(
            history,
            scene_progress=scene_progress,
            relation_delta=relation_delta,
        )
        current_location = _memory_summary.current_location_summary(
            session,
            scene_progress=scene_progress,
        )
        current_companions = _memory_summary.current_companion_summary(
            present_participants=present_participants,
            offstage_participants=offstage_participants,
            participants=participants,
            mode=mode,
            session=session,
        )
        pending_commitments = _memory_summary.pending_commitment_summary(
            history,
            scene_progress=scene_progress,
        )

        return {
            "mode": mode,
            "mode_display": mode_display,
            "recap": recap,
            "cast": cast,
            "relation_drift": relation,
            "perspective": perspective,
            "scene_frame": scene_frame,
            "world": world,
            "recent_commitments": recent_commitments,
            "recent_conflicts": recent_conflicts,
            "recent_actions": recent_actions,
            "major_beats": major_beats,
            "current_goal": current_goal,
            "unresolved_threads": unresolved_threads,
            "current_location": current_location,
            "current_companions": current_companions,
            "pending_commitments": pending_commitments,
            "updated_at": str(session.get("updated_at", "")).strip(),
        }

    def _ensure_memory_store(self, run_id: str) -> bool:
        return self._resolve_memory_store(run_id) is not None

    def _resolve_memory_store(self, run_id: str) -> MarkdownSessionStore | None:
        normalized_run_id = str(run_id or "").strip()
        if not normalized_run_id:
            return None
        cached = self._memory_stores.get(normalized_run_id)
        if cached is not None:
            return cached
        try:
            if callable(self._memory_store_resolver):
                resolved = self._memory_store_resolver(normalized_run_id)
                if resolved is not None:
                    self._memory_stores[normalized_run_id] = resolved
                    return resolved
            config = Config()
            config.update({"paths": {"sessions": str(self.runs_root / normalized_run_id / "__session_memory_cache")}})
            resolved = MarkdownSessionStore(PathProvider(config))
            self._memory_stores[normalized_run_id] = resolved
            return resolved
        except Exception:
            return None

    _trim_summary_text = staticmethod(_text_utils.trim_summary_text)
    _build_last_entry_preview = staticmethod(_text_utils.build_last_entry_preview)

    def _build_file_urls(self, run_id: str, session: dict[str, Any]) -> dict[str, str]:
        session_id = str(session.get("session_id", "")).strip()
        urls: dict[str, str] = {}
        run_dir = self.runs_root / run_id
        session_relative = self._relative_to_run_dir(self._session_file(run_id, session_id), run_dir)
        if session_relative is not None:
            urls["session"] = self._file_url(run_id, session_relative)
        pending_path_text = str(session.get("pending_turn", {}).get("payload_path", "")).strip()
        if pending_path_text:
            pending_path = Path(pending_path_text)
        else:
            pending_path = None
        if pending_path and pending_path.exists():
            pending_relative = self._relative_to_run_dir(pending_path, run_dir)
            if pending_relative is not None:
                urls["pending_turn_payload"] = self._file_url(run_id, pending_relative)
        return urls

    _build_scene_switch_note = staticmethod(_text_utils.build_scene_switch_note)
    _entry_to_memory_text = staticmethod(_text_utils.entry_to_memory_text)

    def _sessions_root(self, run_id: str) -> Path:
        return self.runs_root / run_id / "dialogue"

    def _session_dir(self, run_id: str, session_id: str) -> Path:
        return self._sessions_root(run_id) / session_id

    def _session_file(self, run_id: str, session_id: str) -> Path:
        return self._session_dir(run_id, session_id) / "session.json"

    def _file_url(self, run_id: str, relative_path: Path) -> str:
        return f"/api/web/runs/{run_id}/files/{relative_path.as_posix()}"

    @staticmethod
    def _relative_to_run_dir(path: Path, run_dir: Path) -> Path | None:
        return relative_to_run_dir(path, run_dir)

    @staticmethod
    def _relative_candidates(path: Path, run_dir: Path) -> list[tuple[Path, Path]]:
        return relative_candidates(path, run_dir)

    @staticmethod
    def _normalized_parts(path: Path) -> tuple[str, ...]:
        return normalized_parts(path)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        return read_json(path)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        write_json(path, payload)
