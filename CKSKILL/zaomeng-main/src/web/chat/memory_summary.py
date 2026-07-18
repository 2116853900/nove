from __future__ import annotations

from typing import Any

from src.web.chat.text_utils import trim_summary_text


def recent_commitment_summary(history: list[dict[str, Any]], *, limit: int = 3) -> str:
    keywords = ("会", "要", "答应", "一定", "明天", "今晚", "回头", "随后", "等会", "改天")
    hits: list[str] = []
    for entry in reversed(history[-12:]):
        speaker = str(entry.get("speaker", "")).strip()
        message = str(entry.get("message", "")).strip()
        if not message or speaker in {"场景提示", "旁白"}:
            continue
        if not any(keyword in message for keyword in keywords):
            continue
        hits.append(f"{speaker}：{trim_summary_text(message, 42)}")
        if len(hits) >= limit:
            break
    if not hits:
        return ""
    return trim_summary_text("；".join(reversed(hits)), 140)


def recent_conflict_summary(history: list[dict[str, Any]], *, limit: int = 3) -> str:
    keywords = ("别", "不要", "不能", "不行", "争", "吵", "怒", "恨", "怨", "烦", "逼", "质问", "反驳", "冷")
    hits: list[str] = []
    for entry in reversed(history[-12:]):
        speaker = str(entry.get("speaker", "")).strip()
        message = str(entry.get("message", "")).strip()
        if not message:
            continue
        if not any(keyword in message for keyword in keywords):
            continue
        hits.append(f"{speaker or '当前局势'}：{trim_summary_text(message, 42)}")
        if len(hits) >= limit:
            break
    if not hits:
        return ""
    return trim_summary_text("；".join(reversed(hits)), 140)


def recent_action_summary(history: list[dict[str, Any]], *, limit: int = 4) -> str:
    action_keywords = ("转身", "抬头", "低头", "看向", "走近", "后退", "推门", "沉默", "笑", "叹", "停住", "顿了顿", "抬手", "握住", "松开")
    hits: list[str] = []
    for entry in reversed(history[-12:]):
        speaker = str(entry.get("speaker", "")).strip()
        message = str(entry.get("message", "")).strip()
        if not message:
            continue
        action = ""
        if "（" in message and "）" in message:
            action = message.split("（", 1)[1].split("）", 1)[0].strip()
        elif "(" in message and ")" in message:
            action = message.split("(", 1)[1].split(")", 1)[0].strip()
        elif any(keyword in message for keyword in action_keywords):
            action = trim_summary_text(message, 36)
        if not action:
            continue
        hits.append(f"{speaker or '有人'}：{trim_summary_text(action, 30)}")
        if len(hits) >= limit:
            break
    if not hits:
        return ""
    return trim_summary_text("；".join(reversed(hits)), 140)


def major_beat_summary(
    session: dict[str, Any],
    transcript: list[dict[str, Any]],
    *,
    event_signals: dict[str, Any],
    limit: int = 3,
) -> str:
    event_rows: list[str] = []
    recent_signals = list(dict(event_signals or {}).get("recent", []) or [])
    for signal in reversed(recent_signals[-6:]):
        kind = str(signal.get("kind", "")).strip()
        if kind not in {
            "scene_transition",
            "cast_enter",
            "cast_exit",
            "time_change",
            "environment_change",
            "atmosphere_shift",
            "beat_complete",
            "relationship_shift",
        }:
            continue
        cue = str(signal.get("cue", "")).strip()
        if cue:
            event_rows.append(trim_summary_text(cue, 44))
        if len(event_rows) >= limit:
            break
    if not event_rows:
        scene_history = list(session.get("scene_history", []) or [])
        if scene_history:
            latest = dict(scene_history[-1] or {})
            transition = str(latest.get("transition_message", "")).strip()
            if transition:
                event_rows.append(trim_summary_text(transition, 44))
    if not event_rows:
        for item in reversed(transcript[-8:]):
            role = str(item.get("role", "")).strip()
            message = str(item.get("message", "")).strip()
            if role in {"scene", "director"} and message:
                event_rows.append(trim_summary_text(message, 44))
                if len(event_rows) >= limit:
                    break
    if not event_rows:
        return ""
    return trim_summary_text("；".join(reversed(event_rows[:limit])), 140)


def current_goal_summary(session: dict[str, Any], *, scene_progress: dict[str, Any]) -> str:
    scene_card = dict(session.get("scene_card", {}) or {})
    goals: list[str] = []
    for value in (
        str(scene_card.get("public_goal", "")).strip(),
        str(scene_card.get("scene_drive", "")).strip(),
        str(scene_card.get("opening_situation", "")).strip(),
    ):
        trimmed = trim_summary_text(value, 48)
        if trimmed and trimmed not in goals:
            goals.append(trimmed)
        if len(goals) >= 2:
            break
    hidden_tension = trim_summary_text(str(scene_card.get("hidden_tension", "")).strip(), 48)
    if hidden_tension:
        goals.append(f"暗线：{hidden_tension}")
    progression_note = trim_summary_text(str(scene_progress.get("progression_note", "")).strip(), 56)
    if progression_note:
        goals.append(f"当前推进：{progression_note}")
    if not goals:
        return ""
    return trim_summary_text("；".join(goals[:3]), 160)


def current_location_summary(session: dict[str, Any], *, scene_progress: dict[str, Any]) -> str:
    scene_card = dict(session.get("scene_card", {}) or {})
    location = str(scene_progress.get("location", "")).strip() or str(scene_card.get("location", "")).strip()
    time_hint = str(scene_progress.get("time_hint", "")).strip() or str(scene_card.get("time_hint", "")).strip()
    atmosphere = str(scene_progress.get("atmosphere_summary", "")).strip() or str(scene_card.get("atmosphere", "")).strip()
    title = str(scene_card.get("title", "")).strip()
    bits = [trim_summary_text(item, 32) for item in (title, location, time_hint) if item]
    if atmosphere:
        bits.append(f"氛围：{trim_summary_text(atmosphere, 24)}")
    if not bits:
        return ""
    return trim_summary_text(" · ".join(bits[:4]), 160)


def current_companion_summary(
    *,
    present_participants: list[str],
    offstage_participants: list[str],
    participants: list[str],
    mode: str,
    session: dict[str, Any],
) -> str:
    companions = list(present_participants or participants)
    if mode == "act":
        controlled = str(session.get("controlled_character", "")).strip()
        companions = [name for name in companions if name != controlled]
    elif mode == "insert":
        self_name = str(dict(session.get("self_insert", {}) or {}).get("display_name", "")).strip()
        companions = [name for name in companions if name != self_name]
    bits: list[str] = []
    if companions:
        bits.append(f"当前同行：{'、'.join(companions[:4])}{'...' if len(companions) > 4 else ''}")
    if offstage_participants:
        bits.append(f"暂未同场：{'、'.join(offstage_participants[:3])}")
    if not bits:
        return ""
    return trim_summary_text("；".join(bits), 160)


def pending_commitment_summary(history: list[dict[str, Any]], *, scene_progress: dict[str, Any]) -> str:
    commitment = recent_commitment_summary(history, limit=3)
    if commitment:
        return trim_summary_text(f"待完成承诺：{commitment}", 180)
    shift_reason = str(scene_progress.get("scene_shift_reason", "")).strip()
    if shift_reason:
        return trim_summary_text(f"当前待推进：{shift_reason}", 180)
    return ""


def unresolved_thread_summary(
    history: list[dict[str, Any]],
    *,
    scene_progress: dict[str, Any],
    relation_delta: dict[str, Any],
    limit: int = 4,
) -> str:
    threads: list[str] = []

    def push(value: str) -> None:
        trimmed = trim_summary_text(str(value).strip(), 56)
        if not trimmed or trimmed in threads:
            return
        threads.append(trimmed)

    promise_keywords = ("会", "要", "答应", "一定", "明天", "今晚", "回头", "随后", "等会", "改天")
    unresolved_keywords = ("还没", "尚未", "先", "稍后", "等我", "回头", "之后", "改日", "待会")
    for entry in reversed(history[-12:]):
        speaker = str(entry.get("speaker", "")).strip() or "有人"
        message = str(entry.get("message", "")).strip()
        if not message:
            continue
        if speaker in {"场景提示", "旁白"}:
            continue
        if any(keyword in message for keyword in promise_keywords):
            push(f"{speaker}还挂着：{message}")
        elif any(keyword in message for keyword in unresolved_keywords):
            push(f"{speaker}还没收口：{message}")
        if len(threads) >= limit:
            break

    if not threads:
        shift_reason = str(scene_progress.get("scene_shift_reason", "")).strip()
        if shift_reason:
            push(f"当前待转场：{shift_reason}")

    if len(threads) < limit and relation_delta:
        for pair_key, delta in list(relation_delta.items())[:2]:
            metrics: list[str] = []
            for field, label in (("trust", "信任"), ("affection", "好感"), ("hostility", "敌意"), ("ambiguity", "摇摆")):
                change = int(dict(delta or {}).get(field, 0) or 0)
                if change:
                    metrics.append(f"{label}{change:+d}")
            if metrics:
                push(f"{pair_key}还在变化：{'、'.join(metrics)}")
            if len(threads) >= limit:
                break

    if not threads:
        return ""
    return trim_summary_text("；".join(reversed(threads[:limit])), 180)


def branch_memory_seed_text(summary: dict[str, Any]) -> str:
    recap = str(summary.get("recap", "")).strip()
    cast = str(summary.get("cast", "")).strip()
    relation = str(summary.get("relation_drift", "") or summary.get("relation", "")).strip()
    scene = str(summary.get("scene_frame", "") or summary.get("scene", "")).strip()
    world = str(summary.get("world", "")).strip()
    current_location = str(summary.get("current_location", "")).strip()
    current_companions = str(summary.get("current_companions", "")).strip()
    pending_commitments = str(summary.get("pending_commitments", "")).strip()
    parts = [
        part
        for part in (recap, cast, relation, scene, world, current_location, current_companions, pending_commitments)
        if part
    ]
    return " / ".join(parts[:5])


__all__ = [
    "branch_memory_seed_text",
    "current_companion_summary",
    "current_goal_summary",
    "current_location_summary",
    "major_beat_summary",
    "pending_commitment_summary",
    "recent_action_summary",
    "recent_commitment_summary",
    "recent_conflict_summary",
    "unresolved_thread_summary",
]
