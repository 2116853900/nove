from __future__ import annotations

import re
from typing import Any

SCENE_ENTER_TOKENS = ("进门", "入内", "走进", "转入", "移步", "到了", "回到", "落座", "入座", "上楼", "进屋", "推门而入")
SCENE_EXIT_TOKENS = ("出去", "离开", "退场", "回房", "回家", "出门", "走远", "散去", "下楼", "离席")
ACTION_TOKENS = ("抬头", "低头", "笑", "沉默", "转身", "皱眉", "顿住", "垂眼", "抿唇", "抬眼", "偏头", "停住", "看向")
ATMOSPHERE_TOKENS = ("暧昧", "尴尬", "紧张", "安静", "压抑", "冷场", "发僵", "僵住", "沉下来", "静了一拍", "气氛")
ENVIRONMENT_TOKENS = ("雨", "雪", "风", "雷", "灯", "烛", "门外", "脚步声", "敲门", "天色", "夜色", "天光", "雾", "潮气")
LEAVE_TOKENS = (
    "离开",
    "离席",
    "退场",
    "告退",
    "先走",
    "走吧",
    "退下",
    "走了",
    "离去",
    "回房",
    "回家",
    "回去了",
    "退出",
)
RETURN_TOKENS = (
    "回来",
    "回来了",
    "折返",
    "再入",
    "再至",
    "现身",
    "又到了",
    "入场",
    "进来",
    "进门",
    "重回",
)
TIME_HINT_SEQUENCE = (
    "拂晓",
    "清晨",
    "早晨",
    "上午",
    "中午",
    "午后",
    "下午",
    "傍晚",
    "黄昏",
    "晚上",
    "入夜",
    "夜里",
    "夜深",
    "深夜",
    "半夜",
    "凌晨",
    "天亮",
)
TIME_HINT_ALIASES = {
    "早上": "早晨",
    "晌午": "中午",
    "今晚": "晚上",
    "夜间": "夜里",
    "入夜": "晚上",
    "更深": "夜深",
    "三更": "夜深",
    "四更": "深夜",
    "五更": "凌晨",
}
TIME_FORWARD_CUES = (
    ("掌灯", "晚上"),
    ("灯都亮了", "晚上"),
    ("天色暗了", "傍晚"),
    ("天都黑了", "晚上"),
    ("夜色深了", "夜深"),
    ("夜更深了", "夜深"),
    ("已到深夜", "深夜"),
    ("已近凌晨", "凌晨"),
)
TIME_DRIFT_CUES = ("过了一会", "过了许久", "片刻后", "半晌", "良久", "随后", "一阵后", "再过一阵", "不多时")


def infer_time_hint(transcript: list[dict[str, Any]]) -> str:
    for item in reversed(list(transcript or [])[-14:]):
        message = str(item.get("message", "")).strip()
        if not message:
            continue
        for token in TIME_HINT_SEQUENCE + tuple(TIME_HINT_ALIASES.keys()):
            if token in message:
                return canonical_time_hint(token)
        for cue, target in TIME_FORWARD_CUES:
            if cue in message:
                return target
    return ""


def merge_time_hint(
    *,
    incoming: str,
    base: str,
    history: list[dict[str, Any]],
    scene_hint: str = "",
    allow_history_drift: bool = True,
) -> str:
    incoming_hint = canonical_time_hint(incoming)
    base_hint = canonical_time_hint(base)
    scene_base = canonical_time_hint(scene_hint)
    current = base_hint or scene_base
    if incoming_hint:
        if not current:
            return incoming_hint
        if time_hint_rank(incoming_hint) >= time_hint_rank(current):
            return incoming_hint
        return current
    if allow_history_drift and current and history_has_time_drift(history):
        return advance_time_hint(current)
    return current


def canonical_time_hint(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return TIME_HINT_ALIASES.get(text, text)


def time_hint_rank(value: str) -> int:
    canonical = canonical_time_hint(value)
    try:
        return TIME_HINT_SEQUENCE.index(canonical)
    except ValueError:
        return -1


def advance_time_hint(value: str) -> str:
    rank = time_hint_rank(value)
    if rank < 0:
        return canonical_time_hint(value)
    if rank >= len(TIME_HINT_SEQUENCE) - 1:
        return TIME_HINT_SEQUENCE[-1]
    return TIME_HINT_SEQUENCE[rank + 1]


def history_has_time_drift(history: list[dict[str, Any]]) -> bool:
    recent_messages = [str(item.get("message", "")).strip() for item in list(history or [])[-8:] if str(item.get("message", "")).strip()]
    return any(cue in message for message in recent_messages for cue in TIME_DRIFT_CUES)


def infer_departed_participants(participants: list[str], history: list[dict[str, Any]]) -> set[str]:
    departed: set[str] = set()
    recent = list(history or [])[-16:]
    for entry in recent:
        speaker = str(entry.get("speaker", "")).strip()
        message = str(entry.get("message", "")).strip()
        if not message:
            continue
        for name in participants:
            if name not in message:
                continue
            if speaker not in {"旁白", "场景提示"} and speaker != name:
                continue
            if contains_return_signal(message, name):
                departed.discard(name)
                continue
            if contains_leave_signal(message, name):
                departed.add(name)
        if speaker in participants and self_exit_signal(message):
            departed.add(speaker)
    return departed


def infer_returned_participants(participants: list[str], history: list[dict[str, Any]]) -> set[str]:
    returned: set[str] = set()
    recent = list(history or [])[-16:]
    for entry in recent:
        speaker = str(entry.get("speaker", "")).strip()
        message = str(entry.get("message", "")).strip()
        if not message:
            continue
        for name in participants:
            if name not in message:
                continue
            if speaker not in {"旁白", "场景提示"} and speaker != name:
                continue
            if contains_return_signal(message, name):
                returned.add(name)
        if speaker in participants and self_return_signal(message):
            returned.add(speaker)
    return returned


def contains_leave_signal(text: str, name: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    if contains_stay_signal(compact, name):
        return False
    for token in LEAVE_TOKENS:
        if (
            f"{name}{token}" in compact
            or f"{token}{name}" in compact
            or re.search(re.escape(name) + r".{0,4}" + re.escape(token), compact)
            or re.search(re.escape(token) + r".{0,4}" + re.escape(name), compact)
        ):
            return True
    return False


def contains_return_signal(text: str, name: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    for token in RETURN_TOKENS:
        if (
            f"{name}{token}" in compact
            or f"{token}{name}" in compact
            or re.search(re.escape(name) + r".{0,4}" + re.escape(token), compact)
            or re.search(re.escape(token) + r".{0,4}" + re.escape(name), compact)
        ):
            return True
    return False


def contains_stay_signal(text: str, name: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    patterns = (
        rf"只剩[^。！？；，,]*{re.escape(name)}",
        rf"只留下[^。！？；，,]*{re.escape(name)}",
        rf"留在[^。！？；，,]*{re.escape(name)}",
        rf"{re.escape(name)}[^。！？；，,]*还在",
        rf"{re.escape(name)}[^。！？；，,]*仍在",
    )
    return any(re.search(pattern, compact) for pattern in patterns)


def self_exit_signal(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    return any(
        token in compact
        for token in ("我先走", "我先告退", "我先退下", "我先回房", "我先回家", "我先离开", "我先撤了", "容我告退")
    )


def self_return_signal(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    return any(token in compact for token in ("我回来了", "我又回来了", "我进门了", "我回到这里", "我回来了，", "我回来了。"))


__all__ = [
    "ACTION_TOKENS",
    "ATMOSPHERE_TOKENS",
    "ENVIRONMENT_TOKENS",
    "LEAVE_TOKENS",
    "RETURN_TOKENS",
    "SCENE_ENTER_TOKENS",
    "SCENE_EXIT_TOKENS",
    "TIME_DRIFT_CUES",
    "TIME_FORWARD_CUES",
    "TIME_HINT_ALIASES",
    "TIME_HINT_SEQUENCE",
    "advance_time_hint",
    "canonical_time_hint",
    "contains_leave_signal",
    "contains_return_signal",
    "contains_stay_signal",
    "history_has_time_drift",
    "infer_departed_participants",
    "infer_returned_participants",
    "infer_time_hint",
    "merge_time_hint",
    "self_exit_signal",
    "self_return_signal",
    "time_hint_rank",
]
