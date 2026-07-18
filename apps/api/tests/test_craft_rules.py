from __future__ import annotations

from app.craft import (
    CKSKILL_RULESET_VERSION,
    build_writing_contract,
    deterministic_craft_issues,
    normalize_writing_profile,
)
from app.memory.context_budget import ContextBudget, ContextBudgeter
from app.models import Novel, OutlineNode
from app.services_outline import OutlineService
from sqlalchemy.orm import Session
import pytest
from fastapi import HTTPException

from app.routes import add_writing_pattern, confirm_chapter, get_writing_health
from app.schemas import ConfirmRequest, WritingPatternCreate
from app.services import ChapterService
from app.models import Chapter
from app.agents.auditor import attach_evidence_metadata


def complete_profile() -> dict:
    return {
        "strict_workflow": True,
        "protagonist_name": "林远",
        "protagonist_desire": "找到父亲失踪的真相",
        "protagonist_flaw": "遇到亲情线索时会冒险越界",
        "world_scale": "多域/大陆",
        "power_system": "技术权限与资源等级",
        "golden_finger": "信标译码能力",
        "golden_finger_cost": "每次强行译码都会暴露坐标",
        "antagonist_mirror": "对手同样追求真相，但选择控制所有信息",
        "anti_trope": "关键胜利不能来自无代价的新能力",
        "hard_constraints": ["通讯存在八分钟延迟", "燃料不足时不能跃迁"],
    }


def complete_brief() -> dict:
    return {
        "goal": "确认信标来源",
        "conflict": "燃料不足且队友反对改变航向",
        "cost": "暴露备用航线并消耗最后一根燃料棒",
        "time_anchor": "航行第 812 天夜",
        "chapter_span": "连续两小时",
        "gap_from_previous": "紧接上一章",
        "countdown": "距离信标关闭两小时",
        "hook": "第二枚信标从山脊后升起",
        "cbn": "林远 | 看见信标坠落 | 决定核对坐标",
        "cpns": [
            "苏晚 | 提出燃料限制 | 阻止改变航向",
            "林远 | 译码信标 | 暴露备用航线",
        ],
        "cen": "第二枚信标 | 从山脊升起 | 迫使众人重新选择",
        "must_cover_nodes": ["锁定信标坐标", "第二枚信标升起"],
        "forbidden_zones": ["提前揭示苏晚身份"],
        "must_events": ["锁定信标坐标"],
        "forbidden_events": ["提前揭示苏晚身份"],
    }


def test_strict_writing_contract_is_versioned_and_ready() -> None:
    contract = build_writing_contract(
        profile=complete_profile(),
        genre="科幻",
        chapter_index=12,
        chapter_title="静默航道",
        brief=complete_brief(),
    )

    assert contract["ready"] is True
    assert contract["gate"]["status"] == "pass"
    assert contract["ruleset"] == CKSKILL_RULESET_VERSION
    assert contract["taskbookOrder"] == [
        "chapter_directive",
        "story_nodes",
        "forbidden_zones",
        "style_guidance",
        "dynamic_context",
    ]
    assert contract["provenance"]
    assert all(item["sourcePath"].startswith("CKSKILL/") for item in contract["provenance"])


def test_strict_contract_blocks_missing_fields_and_placeholders() -> None:
    contract = build_writing_contract(
        profile=complete_profile(),
        genre="悬疑",
        chapter_index=2,
        chapter_title="[待补充]",
        brief={"goal": "{章纲目标}", "conflict": "线索不足"},
    )

    codes = {item["code"] for item in contract["gate"]["blockers"]}
    assert contract["ready"] is False
    assert contract["gate"]["status"] == "blocked"
    assert "placeholder_detected" in codes
    assert "missing_time_anchor" in codes
    assert "missing_cbn" in codes
    assert "invalid_cpns" in codes


def test_deterministic_review_blocks_placeholders_leaks_and_missing_nodes() -> None:
    issues = deterministic_craft_issues(
        "正文开头出现 writingTaskbook 与 [待补充]，然后直接结束。",
        {"must_cover_nodes": ["主角付出不可逆代价"]},
    )

    fatal_types = {item["type"] for item in issues if item["severity"] == "fatal"}
    assert "正文占位符" in fatal_types
    assert "工程信息泄漏" in fatal_types
    assert "结构节点未兑现" in fatal_types
    assert all(item["ruleId"] for item in issues)
    assert all(isinstance(item["blocking"], bool) for item in issues)
    assert all(0 <= item["confidence"] <= 1 for item in issues)
    assert all(set(item["location"]) == {"source", "start", "end", "quote"} for item in issues)


def test_expanded_deslop_checks_cover_reasoning_chains_and_sentence_stutter() -> None:
    content = "".join(["他必须知道这意味着什么。" for _ in range(12)])
    content += "他停。她看。门响。灯灭。风起。钟鸣。人散。夜沉。"

    issues = deterministic_craft_issues(content, {})
    issue_types = {item["type"] for item in issues}

    assert "AI 痕迹/推理链过密" in issue_types
    assert "AI 痕迹/连续碎句" in issue_types
    assert all(item["ruleId"] == "CK-DESLOP-PROSE-TICS" for item in issues)


def test_audit_finding_metadata_is_uniform_and_locatable() -> None:
    issue = attach_evidence_metadata(
        {
            "severity": "fatal",
            "type": "禁止事件",
            "evidence": "越过封锁线",
            "evidenceQuote": "越过封锁线",
        },
        "林远最终越过封锁线，暴露了坐标。",
    )

    assert issue["ruleId"] == "CK-PLAN-CHAPTER-CONTRACT"
    assert issue["blocking"] is True
    assert issue["confidence"] == pytest.approx(0.98)
    assert issue["location"] == {
        "source": "content",
        "start": 4,
        "end": 9,
        "quote": "越过封锁线",
    }


def test_non_opening_strict_contract_requires_time_gap_and_carries_previous_cen() -> None:
    brief = complete_brief()
    brief.pop("gap_from_previous")
    previous = {
        "chapterIndex": 11,
        "title": "失控信标",
        "cen": "信标 | 突然熄灭 | 迫使林远改变航向",
        "chapterEndOpenQuestion": "谁关闭了信标？",
    }

    contract = build_writing_contract(
        profile=complete_profile(),
        genre="科幻",
        chapter_index=12,
        chapter_title="静默航道",
        brief=brief,
        dynamic_context={"previousChapterContract": previous},
    )

    assert "missing_gap_from_previous" in {
        item["code"] for item in contract["gate"]["blockers"]
    }
    assert contract["taskbook"]["dynamic_context"]["previous_chapter_contract"] == previous


def test_normalized_profile_requires_no_implicit_magic_cost() -> None:
    profile = normalize_writing_profile(
        {"golden_finger": "无限回档", "hard_constraints": "规则一\n规则二"}
    )
    assert profile["golden_finger"] == "无限回档"
    assert profile["golden_finger_cost"] == ""
    assert profile["hard_constraints"] == ["规则一", "规则二"]


def test_context_budget_never_drops_locked_rules() -> None:
    locked = [
        {"rule": f"锁定规则 {index} " + "不可删除" * 200, "locked": True}
        for index in range(4)
    ]
    ordinary = [
        {"rule": f"普通规则 {index} " + "可裁剪" * 200, "locked": False}
        for index in range(8)
    ]
    budget = ContextBudget.create(
        context_window=8192,
        max_output_tokens=2048,
        task_tokens=1024,
    )
    fitted, _ = ContextBudgeter(budget).fit(
        {
            "rules": [*locked, *ordinary],
            "outline": {"hierarchy": []},
            "recentConfirmedChapters": [],
            "memory": [],
            "entities": [],
            "plotThreads": [],
            "characterStates": [],
            "locationStates": [],
        }
    )

    assert [item["rule"] for item in fitted["rules"] if item["locked"]] == [
        item["rule"] for item in locked
    ]


def test_strict_outline_commit_rejects_incomplete_chapter_contract(
    session: Session,
) -> None:
    novel = session.get(Novel, "starfarer")
    parent = session.get(OutlineNode, "arc1")
    assert novel is not None and parent is not None
    novel.writing_profile = complete_profile()
    session.commit()

    with pytest.raises(ValueError, match="规划门禁未通过"):
        OutlineService(session)._commit_drafts(
            novel=novel,
            parent=parent,
            resolved_kind="chapter",
            drafts=[
                {
                    "kind": "chapter",
                    "title": "第 14 章 · 合同不完整",
                    "details": {"goal": "推进冲突", "conflict": "资源不足"},
                }
            ],
            draft_source="test",
            create_chapters=True,
            max_pos=20,
            max_chapter_index=13,
            locked_sibling_count=0,
        )


def test_strict_confirm_requires_audit_for_current_version(session: Session) -> None:
    novel = session.get(Novel, "starfarer")
    chapter = session.get(Chapter, "c12")
    assert novel is not None and chapter is not None
    novel.writing_profile = complete_profile()
    chapter.brief = complete_brief()
    version = ChapterService(session).create_version(
        chapter,
        content="锁定信标坐标。第二枚信标升起。" * 40,
        title=chapter.title,
        source="user",
        base_version_id=chapter.current_version_id,
    )
    assert chapter.current_version_id == version.id

    with pytest.raises(HTTPException) as captured:
        confirm_chapter(chapter.id, ConfirmRequest(), session)

    assert captured.value.status_code == 409
    assert "先完成质量检查" in str(captured.value.detail)


def test_project_learning_is_append_only_and_health_is_read_only(
    session: Session,
) -> None:
    novel = session.get(Novel, "starfarer")
    assert novel is not None
    first = add_writing_pattern(
        novel.id,
        WritingPatternCreate(
            pattern_type="hook",
            description="章末用角色选择而不是旁白总结制造追读动机",
            importance="high",
        ),
        session,
    )
    second = add_writing_pattern(
        novel.id,
        WritingPatternCreate(
            pattern_type="hook",
            description="章末用角色选择而不是旁白总结制造追读动机",
            importance="high",
        ),
        session,
    )
    assert first["status"] == "success"
    assert second["writingProfile"]["learned_patterns"].count(first["learned"]) == 1

    health = get_writing_health(novel.id, session)
    assert health["ruleset"] == CKSKILL_RULESET_VERSION
    assert health["chapters"] >= 1
    assert health["provenance"]
