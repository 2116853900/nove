from __future__ import annotations

import difflib
from typing import Any


def paragraph_diff(left: str, right: str) -> dict[str, Any]:
    """Paragraph-level diff for version comparison UI."""
    left_paras = [p for p in (left or "").split("\n\n") if p != ""]
    right_paras = [p for p in (right or "").split("\n\n") if p != ""]
    matcher = difflib.SequenceMatcher(a=left_paras, b=right_paras)
    left_rows: list[dict[str, Any]] = []
    right_rows: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for idx in range(i1, i2):
                left_rows.append({"text": left_paras[idx], "change": "equal"})
                right_rows.append({"text": right_paras[j1 + (idx - i1)], "change": "equal"})
        elif tag == "replace":
            for idx in range(i1, i2):
                left_rows.append({"text": left_paras[idx], "change": "delete"})
            for idx in range(j1, j2):
                right_rows.append({"text": right_paras[idx], "change": "insert"})
        elif tag == "delete":
            for idx in range(i1, i2):
                left_rows.append({"text": left_paras[idx], "change": "delete"})
        elif tag == "insert":
            for idx in range(j1, j2):
                right_rows.append({"text": right_paras[idx], "change": "insert"})
    return {
        "left": left_rows,
        "right": right_rows,
        "stats": {
            "leftParagraphs": len(left_paras),
            "rightParagraphs": len(right_paras),
            "deleted": sum(1 for r in left_rows if r["change"] == "delete"),
            "inserted": sum(1 for r in right_rows if r["change"] == "insert"),
            "equal": sum(1 for r in left_rows if r["change"] == "equal"),
        },
    }
