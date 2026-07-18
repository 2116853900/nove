from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Any


_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def estimate_text_tokens(text: str) -> int:
    """Conservative tokenizer-independent estimate for mixed Chinese/Latin text."""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    non_cjk = max(0, len(text) - cjk)
    return cjk + math.ceil(non_cjk / 3.5)


def estimate_tokens(value: Any) -> int:
    if isinstance(value, str):
        return estimate_text_tokens(value)
    return estimate_text_tokens(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    )


def truncate_text(text: str, token_limit: int) -> str:
    if token_limit <= 0:
        return ""
    if estimate_text_tokens(text) <= token_limit:
        return text
    low, high = 0, len(text)
    while low < high:
        mid = (low + high + 1) // 2
        if estimate_text_tokens(text[:mid]) <= token_limit:
            low = mid
        else:
            high = mid - 1
    return text[:low].rstrip() + "…"


@dataclass(frozen=True)
class ContextBudget:
    context_window: int
    output_reserve: int
    task_reserve: int
    safety_reserve: int
    authoritative_limit: int

    @classmethod
    def create(
        cls,
        *,
        context_window: int,
        max_output_tokens: int,
        task_tokens: int,
    ) -> "ContextBudget":
        window = max(8192, int(context_window or 32768))
        output = max(1024, int(max_output_tokens or 4096))
        safety = max(2048, math.ceil(window * 0.08))
        available = max(2048, window - output - safety - max(0, task_tokens))
        return cls(
            context_window=window,
            output_reserve=output,
            task_reserve=max(0, task_tokens),
            safety_reserve=safety,
            authoritative_limit=min(32000, available),
        )


class ContextBudgeter:
    SECTION_RATIOS = {
        "rules": 0.10,
        "outline": 0.16,
        "recentConfirmedChapters": 0.16,
        "memory": 0.22,
        "entities": 0.15,
        "plotThreads": 0.08,
        "characterStates": 0.08,
        "locationStates": 0.05,
    }

    DROP_ORDER = (
        "memory",
        "entities",
        "plotThreads",
        "recentConfirmedChapters",
        "characterStates",
        "locationStates",
        "outline",
        "rules",
    )

    def __init__(self, budget: ContextBudget):
        self.budget = budget

    def fit(self, context: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        result = dict(context)
        before = {key: estimate_tokens(result.get(key)) for key in self.SECTION_RATIOS}
        dropped: dict[str, int] = {}

        for key, ratio in self.SECTION_RATIOS.items():
            cap = max(256, int(self.budget.authoritative_limit * ratio))
            value = result.get(key)
            if key == "outline" and isinstance(value, dict):
                hierarchy = list(value.get("hierarchy") or [])
                kept, count = self._trim_list(hierarchy, cap, drop_from_front=True)
                result[key] = {**value, "hierarchy": kept}
                dropped[key] = count
            elif key == "rules" and isinstance(value, list):
                kept, count = self._trim_rules(value, cap)
                result[key] = kept
                dropped[key] = count
            elif isinstance(value, list):
                drop_from_front = key == "recentConfirmedChapters"
                kept, count = self._trim_list(value, cap, drop_from_front=drop_from_front)
                result[key] = kept
                dropped[key] = count

        while estimate_tokens(result) > self.budget.authoritative_limit:
            changed = False
            for key in self.DROP_ORDER:
                if self._drop_one(result, key):
                    dropped[key] = dropped.get(key, 0) + 1
                    changed = True
                    break
            if not changed:
                break

        after = {key: estimate_tokens(result.get(key)) for key in self.SECTION_RATIOS}
        report = {
            "contextWindow": self.budget.context_window,
            "authoritativeLimit": self.budget.authoritative_limit,
            "estimatedTokens": estimate_tokens(result),
            "outputReserve": self.budget.output_reserve,
            "taskReserve": self.budget.task_reserve,
            "safetyReserve": self.budget.safety_reserve,
            "sectionTokensBefore": before,
            "sectionTokensAfter": after,
            "droppedItems": {key: value for key, value in dropped.items() if value},
            "truncated": any(dropped.values()),
        }
        return result, report

    @staticmethod
    def _trim_rules(items: list[Any], token_limit: int) -> tuple[list[Any], int]:
        locked = [item for item in items if isinstance(item, dict) and item.get("locked")]
        ordinary = [item for item in items if item not in locked]
        kept = [*locked, *ordinary]
        dropped = 0
        while ordinary and estimate_tokens(kept) > token_limit:
            ordinary.pop()
            dropped += 1
            kept = [*locked, *ordinary]
        return kept, dropped

    @staticmethod
    def _trim_list(
        items: list[Any], token_limit: int, *, drop_from_front: bool
    ) -> tuple[list[Any], int]:
        kept = list(items)
        dropped = 0
        while kept and estimate_tokens(kept) > token_limit:
            if len(kept) == 1:
                break
            kept.pop(0 if drop_from_front else -1)
            dropped += 1
        return kept, dropped

    @staticmethod
    def _drop_one(context: dict[str, Any], key: str) -> bool:
        value = context.get(key)
        if key == "outline" and isinstance(value, dict):
            hierarchy = value.get("hierarchy") or []
            if len(hierarchy) > 1:
                context[key] = {**value, "hierarchy": hierarchy[1:]}
                return True
            return False
        if not isinstance(value, list) or not value:
            return False
        if key == "rules":
            removable = next(
                (index for index in range(len(value) - 1, -1, -1) if not value[index].get("locked")),
                None,
            )
            if removable is None:
                return False
            value.pop(removable)
            return True
        value.pop(0 if key == "recentConfirmedChapters" else -1)
        return True
