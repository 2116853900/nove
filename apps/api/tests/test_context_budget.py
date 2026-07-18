from __future__ import annotations

from app.memory.context_budget import (
    ContextBudget,
    ContextBudgeter,
    estimate_text_tokens,
    estimate_tokens,
    truncate_text,
)


def test_token_estimate_and_truncation_handle_chinese() -> None:
    text = "暗渊确认神力只够点亮一盏灯。" * 20
    assert estimate_text_tokens(text) >= 200
    truncated = truncate_text(text, 60)
    assert truncated.endswith("…")
    assert estimate_text_tokens(truncated) <= 61


def test_context_budget_preserves_locked_rules_and_current_outline() -> None:
    budget = ContextBudget.create(
        context_window=8192,
        max_output_tokens=2048,
        task_tokens=1024,
    )
    context = {
        "novel": {"title": "长篇"},
        "rules": [
            {"rule": "锁定规则" * 100, "locked": True},
            *[{"rule": f"普通规则{i}" * 100, "locked": False} for i in range(12)],
        ],
        "outline": {
            "hierarchy": [
                {"kind": "volume", "details": {"summary": "卷" * 1000}},
                {"kind": "arc", "details": {"summary": "弧" * 1000}},
                {"kind": "chapter", "details": {"goal": "章" * 1000}},
            ]
        },
        "recentConfirmedChapters": [
            {"content": str(i) * 1200} for i in range(5)
        ],
        "memory": [str(i) * 1200 for i in range(10)],
        "entities": [{"summary": str(i) * 800} for i in range(20)],
        "plotThreads": [{"latest": str(i) * 500} for i in range(12)],
        "characterStates": [{"notes": str(i) * 400} for i in range(15)],
        "locationStates": [{"notes": str(i) * 400} for i in range(10)],
    }

    fitted, report = ContextBudgeter(budget).fit(context)

    assert estimate_tokens(fitted) <= budget.authoritative_limit
    assert any(item["locked"] for item in fitted["rules"])
    assert fitted["outline"]["hierarchy"][-1]["kind"] == "chapter"
    assert report["truncated"] is True
    assert report["droppedItems"]
