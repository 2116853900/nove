from __future__ import annotations

from sqlalchemy.orm import Session

from app.agents.style import heuristic_selection_edit
from app.models import Chapter
from app.services import SelectionEditService


def test_heuristic_operations() -> None:
    text = "他看见了信标。"
    assert "细节" in heuristic_selection_edit(operation="expand", selected_text=text) or len(
        heuristic_selection_edit(operation="expand", selected_text=text)
    ) > len(text)
    assert len(heuristic_selection_edit(operation="shrink", selected_text=text * 3)) < len(text * 3)
    assert "「" in heuristic_selection_edit(operation="dialogue", selected_text="快走")


def test_selection_edit_returns_candidate_without_writing(session: Session) -> None:
    chapter = session.get(Chapter, "c1")
    assert chapter is not None and chapter.current_version_id
    content = "开头段落。\n\n中间需要改写的句子。\n\n结尾段落。"
    start = content.index("中间需要改写的句子。")
    end = start + len("中间需要改写的句子。")
    before_version = chapter.current_version_id

    result = SelectionEditService(session).edit(
        chapter,
        operation="rewrite",
        start=start,
        end=end,
        selected_text="中间需要改写的句子。",
        content=content,
        instruction="更有画面感",
    )
    assert result["applied"] is False
    assert result["originalText"] == "中间需要改写的句子。"
    assert result["candidateText"]
    assert result["mergedContent"].startswith("开头段落。")
    assert result["instruction"] == "更有画面感"
    assert chapter.current_version_id == before_version


def test_selection_edit_rejects_mismatched_text(session: Session) -> None:
    chapter = session.get(Chapter, "c1")
    assert chapter is not None
    content = "abcdefghij"
    try:
        SelectionEditService(session).edit(
            chapter,
            operation="expand",
            start=0,
            end=4,
            selected_text="zzzz",
            content=content,
        )
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "selected_text" in str(exc)
