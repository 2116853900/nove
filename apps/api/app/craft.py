from __future__ import annotations

import re
from typing import Any


CKSKILL_RULESET_VERSION = "2026.07"

WORKFLOW_STAGES = [
    "prewrite",
    "context",
    "plan",
    "draft",
    "continuity",
    "audit",
    "polish",
    "confirm",
    "memory",
]

TASKBOOK_ORDER = [
    "chapter_directive",
    "story_nodes",
    "forbidden_zones",
    "style_guidance",
    "dynamic_context",
]

RULE_PROVENANCE = [
    {
        "ruleId": "CK-INIT-SUFFICIENCY",
        "sourcePath": "CKSKILL/webnovel-writer-master/webnovel-writer/skills/webnovel-init/SKILL.md",
        "sourceLine": 154,
        "scope": "init,blueprint",
        "severity": "blocking",
    },
    {
        "ruleId": "CK-CONSTITUTION-VERIFIABLE",
        "sourcePath": "CKSKILL/novel-writer-main/templates/commands/constitution.md",
        "sourceLine": 202,
        "scope": "init,policy",
        "severity": "blocking",
    },
    {
        "ruleId": "CK-WRITE-TASKBOOK-ORDER",
        "sourcePath": "CKSKILL/webnovel-writer-master/webnovel-writer/skills/webnovel-write/SKILL.md",
        "sourceLine": 75,
        "scope": "context,draft",
        "severity": "blocking",
    },
    {
        "ruleId": "CK-PLAN-CHAPTER-CONTRACT",
        "sourcePath": "CKSKILL/webnovel-writer-master/webnovel-writer/skills/webnovel-plan/SKILL.md",
        "sourceLine": 144,
        "scope": "outline,prewrite",
        "severity": "blocking",
    },
    {
        "ruleId": "CK-WRITE-SINGLE-REVIEW",
        "sourcePath": "CKSKILL/webnovel-writer-master/webnovel-writer/skills/webnovel-write/SKILL.md",
        "sourceLine": 162,
        "scope": "audit,repair",
        "severity": "blocking",
    },
    {
        "ruleId": "CK-WRITE-ANTI-AI",
        "sourcePath": "CKSKILL/webnovel-writer-master/webnovel-writer/skills/webnovel-write/SKILL.md",
        "sourceLine": 170,
        "scope": "draft,audit,polish",
        "severity": "warning",
    },
    {
        "ruleId": "CK-DESLOP-PROSE-TICS",
        "sourcePath": "CKSKILL/oh-story-claudecode-main/skills/story-long-write/scripts/check-ai-patterns.js",
        "sourceLine": 724,
        "scope": "draft,audit,polish",
        "severity": "warning",
    },
    {
        "ruleId": "CK-HUMANIZER-AI-VOCAB",
        "sourcePath": "CKSKILL/Humanizer-zh-main/SKILL.md",
        "sourceLine": 168,
        "scope": "draft,audit,polish",
        "severity": "warning",
    },
    {
        "ruleId": "CK-REVIEW-BLOCKING-DECISION",
        "sourcePath": "CKSKILL/webnovel-writer-master/webnovel-writer/skills/webnovel-review/SKILL.md",
        "sourceLine": 114,
        "scope": "audit,confirm",
        "severity": "blocking",
    },
    {
        "ruleId": "CK-LEARN-APPEND-ONLY",
        "sourcePath": "CKSKILL/webnovel-writer-master/webnovel-writer/skills/webnovel-learn/SKILL.md",
        "sourceLine": 29,
        "scope": "learning",
        "severity": "required",
    },
    {
        "ruleId": "CK-DOCTOR-READ-ONLY",
        "sourcePath": "CKSKILL/webnovel-writer-master/webnovel-writer/skills/webnovel-doctor/SKILL.md",
        "sourceLine": 17,
        "scope": "health",
        "severity": "required",
    },
    {
        "ruleId": "CK-NO-CANON-COPY",
        "sourcePath": "CKSKILL/webnovel-writer-master/webnovel-writer/skills/webnovel-init/SKILL.md",
        "sourceLine": 109,
        "scope": "research,blueprint",
        "severity": "blocking",
    },
    {
        "ruleId": "CK-EVIDENCE-CONFIDENCE",
        "sourcePath": "CKSKILL/zaomeng-main/zaomeng-skill/references/validation_policy.md",
        "sourceLine": 13,
        "scope": "audit,memory",
        "severity": "blocking",
    },
]

PLACEHOLDER_PATTERNS = (
    re.compile(r"\[待[^\]]*\]"),
    re.compile(r"(?:（|\()?(?:暂名|待补充)(?:）|\))?"),
    re.compile(r"\{(?:占位|章纲目标)[^}]*\}|<(?:占位|章纲目标)[^>]*>"),
)

GENRE_GUIDANCE: dict[str, list[str]] = {
    "玄幻": ["升级、资源与对抗结果必须有可见反馈", "越级胜利必须交代机制与代价"],
    "仙侠": ["境界推进遵守既定阶梯", "术语解释后置，优先呈现选择与代价"],
    "都市": ["写出社会反馈链：他人反应、资源变化、地位变化"],
    "悬疑": ["线索可回溯且可回收", "答案推进同时生成更具体的新问题"],
    "规则怪谈": ["规则先于解释，代价先于胜利", "规则变体必须有已知依据"],
    "科幻": ["技术能力、限制和代价保持一致", "关键破局必须有机制证据"],
    "历史": ["制度、交通和信息传播速度服从时代约束"],
    "古代言情": ["每章至少产生一次关系或利益位置变化"],
    "现代言情": ["情绪变化必须由动作、信息或选择触发"],
}

ANTI_AI_PATTERNS: tuple[tuple[str, re.Pattern[str], int], ...] = (
    ("空泛认知句", re.compile(r"(?:他|她|他们|她们)?(?:深深地)?(?:知道|明白|意识到)[，,:：]?这(?:意味着|代表着)"), 2),
    ("模板转折", re.compile(r"不是[^。！？\n]{2,28}(?:，|,)?而是"), 3),
    ("空泛总结", re.compile(r"(?:这一刻|从这一刻起|命运的齿轮|一切才刚刚开始)"), 2),
    ("过量不确定修饰", re.compile(r"(?:仿佛|似乎|好像)"), 8),
    ("机械递进", re.compile(r"不仅[^。！？\n]{2,36}(?:，|,)?(?:更|而且|还)"), 3),
    ("推理链过密", re.compile(r"(?:知道|明白|意识到|这意味着|因此|所以|必须|需要)"), 12),
    ("比喻标记过密", re.compile(r"(?:仿佛|宛如|如同|犹如|像是)"), 10),
    ("抽象预告收束", re.compile(r"(?:没人知道|谁也不知道|谁也没想到|殊不知|才刚刚开始|拉开(?:序幕|帷幕)|即将(?:开始|来临|降临))"), 2),
    ("AI 高频词汇", re.compile(r"(?:至关重要|深入探讨|不断演变的格局|不可磨灭|彰显(?:了)?|见证(?:了)?|发挥(?:着)?关键作用)"), 3),
    ("公告公文腔", re.compile(r"(?:不得|必须|不可|禁止|严禁|应当|务必|被视为|同样计入)"), 10),
    ("破折号过密", re.compile(r"(?:——|—)"), 10),
)


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _list(value: Any, *, limit: int = 20) -> list[str]:
    if isinstance(value, str):
        values = re.split(r"[\n；;]+", value)
    elif isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = []
    result: list[str] = []
    for item in values:
        text = _text(item)
        if text and text not in result:
            result.append(text)
    return result[:limit]


def normalize_writing_profile(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    bootstrap_status = _text(raw.get("bootstrap_status"))
    if bootstrap_status not in {"", "pending", "running", "complete", "failed"}:
        bootstrap_status = ""
    bootstrap_stage = _text(raw.get("bootstrap_stage"))
    if bootstrap_stage not in {
        "",
        "blueprint",
        "bible",
        "volumes",
        "arcs",
        "chapters",
        "complete",
    }:
        bootstrap_stage = ""
    try:
        bootstrap_progress = max(0, min(100, int(raw.get("bootstrap_progress") or 0)))
    except (TypeError, ValueError):
        bootstrap_progress = 0
    return {
        "ruleset": CKSKILL_RULESET_VERSION,
        "strict_workflow": bool(raw.get("strict_workflow", False)),
        "target_audience": _text(raw.get("target_audience")),
        "platform": _text(raw.get("platform")),
        "protagonist_name": _text(raw.get("protagonist_name")),
        "protagonist_desire": _text(raw.get("protagonist_desire")),
        "protagonist_flaw": _text(raw.get("protagonist_flaw")),
        "world_scale": _text(raw.get("world_scale")),
        "power_system": _text(raw.get("power_system")),
        "golden_finger": _text(raw.get("golden_finger")),
        "golden_finger_cost": _text(raw.get("golden_finger_cost")),
        "antagonist_mirror": _text(raw.get("antagonist_mirror")),
        "anti_trope": _text(raw.get("anti_trope")),
        "hard_constraints": _list(raw.get("hard_constraints"), limit=12),
        "anti_patterns": _list(raw.get("anti_patterns"), limit=12),
        "learned_patterns": _list(raw.get("learned_patterns"), limit=20),
        "bootstrap_status": bootstrap_status,
        "bootstrap_stage": bootstrap_stage,
        "bootstrap_progress": bootstrap_progress,
        "bootstrap_message": _text(raw.get("bootstrap_message")),
        "bootstrap_error": _text(raw.get("bootstrap_error")),
        "bootstrap_draft_source": _text(raw.get("bootstrap_draft_source")),
        "auto_generated": bool(raw.get("auto_generated", False)),
    }


def profile_readiness(profile: Any) -> dict[str, Any]:
    value = normalize_writing_profile(profile)
    required = {
        "protagonist_name": "主角姓名",
        "protagonist_desire": "主角欲望",
        "protagonist_flaw": "主角缺陷",
        "world_scale": "世界规模",
        "power_system": "力量体系",
        "anti_trope": "反套路约束",
    }
    missing = [label for key, label in required.items() if not value[key]]
    if len(value["hard_constraints"]) < 2:
        missing.append("至少两条硬约束")
    if value["golden_finger"] and not value["golden_finger_cost"]:
        missing.append("金手指代价或边界")
    return {
        "ready": not missing,
        "missing": missing,
        "strict": value["strict_workflow"],
        "ruleset": CKSKILL_RULESET_VERSION,
    }


def _has_placeholder(value: Any) -> bool:
    if isinstance(value, dict):
        return any(_has_placeholder(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_placeholder(item) for item in value)
    text = _text(value)
    return bool(text and any(pattern.search(text) for pattern in PLACEHOLDER_PATTERNS))


def _first(brief: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = brief.get(key)
        if value not in (None, "", [], {}):
            return value
    return ""


def _chapter_directive(brief: dict[str, Any]) -> dict[str, Any]:
    nested = brief.get("chapter_directive")
    source = {**brief, **(nested if isinstance(nested, dict) else {})}
    return {
        "goal": _text(_first(source, "goal", "chapter_goal")),
        "conflict": _text(_first(source, "conflict", "obstacle")),
        "cost": _text(_first(source, "cost", "price")),
        "time_anchor": _text(_first(source, "time_anchor", "story_time")),
        "chapter_span": _text(_first(source, "chapter_span", "time_span")),
        "gap_from_previous": _text(_first(source, "gap_from_previous", "previous_gap")),
        "countdown": _text(_first(source, "countdown", "countdown_state")),
        "chapter_end_open_question": _text(
            _first(source, "chapter_end_open_question", "open_question", "hook")
        ),
        "target_words": source.get("target_words"),
    }


def _story_nodes(brief: dict[str, Any]) -> dict[str, Any]:
    nested = brief.get("chapter_directive")
    source = {**brief, **(nested if isinstance(nested, dict) else {})}
    cbn = _text(_first(source, "cbn", "CBN"))
    cpns = _list(_first(source, "cpns", "CPNs"), limit=4)
    cen = _text(_first(source, "cen", "CEN"))
    must_cover = _list(
        _first(source, "must_cover_nodes", "mandatory_nodes", "must_events"),
        limit=8,
    )
    return {
        "cbn": cbn,
        "cpns": cpns,
        "cen": cen,
        "must_cover_nodes": must_cover,
        "must_events": _list(brief.get("must_events"), limit=8),
    }


def _forbidden_zones(brief: dict[str, Any]) -> list[str]:
    nested = brief.get("chapter_directive")
    source = {**brief, **(nested if isinstance(nested, dict) else {})}
    return _list(
        _first(source, "forbidden_zones", "prohibitions", "forbidden_events"),
        limit=10,
    )


def _style_guidance(
    profile: dict[str, Any], genre: str, brief: dict[str, Any]
) -> dict[str, Any]:
    genre_items: list[str] = []
    for key, items in GENRE_GUIDANCE.items():
        if key in genre:
            genre_items.extend(items)
    if not genre_items:
        genre_items = ["冲突前置、解释后置，场景形成动作到结果的闭环"]
    return {
        "genre": genre,
        "genre_guidance": genre_items,
        "protagonist_flaw_guard": profile["protagonist_flaw"],
        "anti_trope": profile["anti_trope"],
        "hard_constraints": profile["hard_constraints"],
        "anti_patterns": profile["anti_patterns"],
        "learned_patterns": profile["learned_patterns"],
        "pace": _text(brief.get("pace")),
        "dialogue_ratio": brief.get("dialogue_ratio"),
        "style_instruction": _text(brief.get("style_instruction")),
    }


def build_writing_contract(
    *,
    profile: Any,
    genre: str,
    chapter_index: int,
    chapter_title: str,
    brief: dict[str, Any] | None,
    dynamic_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_profile = normalize_writing_profile(profile)
    chapter_brief = dict(brief or {})
    directive = _chapter_directive(chapter_brief)
    nodes = _story_nodes(chapter_brief)
    forbidden = _forbidden_zones(chapter_brief)
    style = _style_guidance(normalized_profile, genre, chapter_brief)
    strict = normalized_profile["strict_workflow"]
    dynamic = dynamic_context or {}

    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    def report(code: str, message: str, repair: str, *, blocking: bool) -> None:
        target = blockers if blocking else warnings
        target.append({"code": code, "message": message, "repair": repair})

    if _has_placeholder({"directive": directive, "nodes": nodes, "forbidden": forbidden}):
        report(
            "placeholder_detected",
            "本章合同仍包含待补充、暂名或占位文本。",
            "先在章节细纲中补齐真实目标、实体名和节点，再生成正文。",
            blocking=True,
        )

    required_directive = {
        "goal": "本章目标",
        "conflict": "阻力/冲突",
        "time_anchor": "故事发生时间",
        "chapter_span": "本章经过多久",
        "chapter_end_open_question": "章末未闭合问题",
    }
    for key, label in required_directive.items():
        if directive[key]:
            continue
        report(
            f"missing_{key}",
            f"缺少{label}。",
            f"在章节细纲中补充{label}。",
            blocking=strict,
        )

    if chapter_index > 1 and not directive["gap_from_previous"]:
        report(
            "missing_gap_from_previous",
            "缺少与上一章的时间差。",
            "说明本章紧接、并行或间隔了多长时间。",
            blocking=strict,
        )

    for key, label in (("cbn", "开场动作"), ("cen", "收束变化")):
        if not nodes[key]:
            report(
                f"missing_{key}",
                f"缺少{label}。",
                "补充本章开始或结束时发生的具体动作与变化。",
                blocking=strict,
            )
    if not 2 <= len(nodes["cpns"]) <= 4:
        report(
            "invalid_cpns",
            "中段推进应为 2-4 步。",
            "按故事发生顺序补齐 2-4 个中段推进。",
            blocking=strict,
        )
    if len(nodes["must_cover_nodes"]) > 4:
        report(
            "too_many_mandatory_nodes",
            "必须覆盖节点超过 4 个，章节容易变成任务清单。",
            "只保留开场、收束与 1-2 个核心推进。",
            blocking=strict,
        )
    if len(forbidden) > 5:
        report(
            "too_many_forbidden_zones",
            "本章禁区超过 5 条。",
            "只保留本章绝对不能发生的硬禁区。",
            blocking=False,
        )

    readiness = profile_readiness(normalized_profile)
    if readiness["missing"]:
        report(
            "profile_incomplete",
            "创作档案未完整：" + "、".join(readiness["missing"]),
            "系统会根据故事蓝图自动补齐创作档案。",
            blocking=strict,
        )

    recent_context = []
    for item in (dynamic.get("recentConfirmedChapters") or [])[:3]:
        if not isinstance(item, dict):
            continue
        summary = item.get("summary") if isinstance(item.get("summary"), dict) else {}
        recent_context.append(
            {
                "chapterIndex": item.get("chapterIndex"),
                "title": _text(item.get("title")),
                "summary": _text(summary.get("summary"))[:600],
                "openLoops": _list(summary.get("openLoops"), limit=8),
            }
        )
    status = "blocked" if blockers else ("warning" if warnings else "pass")
    return {
        "ruleset": CKSKILL_RULESET_VERSION,
        "provenance": RULE_PROVENANCE,
        "chapterIndex": chapter_index,
        "chapterTitle": chapter_title,
        "workflow": WORKFLOW_STAGES,
        "taskbookOrder": TASKBOOK_ORDER,
        "strict": strict,
        "ready": not blockers,
        "gate": {
            "stage": "prewrite",
            "status": status,
            "blockers": blockers,
            "warnings": warnings,
            "checks": {
                "profileReady": readiness["ready"],
                "placeholderFree": not _has_placeholder(chapter_brief),
                "directiveReady": all(directive[key] for key in required_directive),
                "storyNodesReady": bool(nodes["cbn"] and 2 <= len(nodes["cpns"]) <= 4 and nodes["cen"]),
                "forbiddenZonesBounded": len(forbidden) <= 5,
            },
        },
        "taskbook": {
            "chapter_directive": directive,
            "story_nodes": nodes,
            "forbidden_zones": forbidden,
            "style_guidance": style,
            "dynamic_context": {
                "recent_chapters": recent_context,
                "active_plot_threads": (dynamic.get("plotThreads") or [])[:8],
                "character_states": (dynamic.get("characterStates") or [])[:15],
                "location_states": (dynamic.get("locationStates") or [])[:10],
                "retrieved_memory_count": len(dynamic.get("memory") or []),
                "retrieval_query": _text(dynamic.get("retrievalQuery")),
                "previous_chapter_contract": dynamic.get("previousChapterContract") or {},
            },
        },
    }


def deterministic_craft_issues(
    content: str, brief: dict[str, Any] | None
) -> list[dict[str, Any]]:
    text = content.strip()
    chapter_brief = brief or {}
    issues: list[dict[str, Any]] = []
    placeholder_match = next(
        (match for pattern in PLACEHOLDER_PATTERNS if (match := pattern.search(text))),
        None,
    )
    if placeholder_match:
        issues.append(
            {
                "severity": "fatal",
                "type": "正文占位符",
                "evidence": placeholder_match.group(0),
                "evidenceQuote": placeholder_match.group(0),
                "evidenceSource": "content",
                "conflictsWith": "可发布正文不得包含占位文本",
                "suggestion": "用实际人物、事件或设定替换占位符后重新审计。",
            }
        )
    leaked = re.search(
        r"(?:chapter_directive|must_cover_nodes|forbidden_zones|authoritativeContext|writingTaskbook|```json)",
        text,
        flags=re.IGNORECASE,
    )
    if leaked:
        issues.append(
            {
                "severity": "fatal",
                "type": "工程信息泄漏",
                "evidence": leaked.group(0),
                "evidenceQuote": leaked.group(0),
                "evidenceSource": "content",
                "conflictsWith": "Writer 只能输出章节正文",
                "suggestion": "删除任务书、字段名或 JSON 围栏，只保留故事正文。",
            }
        )
    nodes = _story_nodes(chapter_brief)
    mandatory = nodes["must_cover_nodes"] or nodes["must_events"]
    for item in mandatory:
        if item and item not in text:
            issues.append(
                {
                    "severity": "fatal",
                    "type": "结构节点未兑现",
                    "evidence": f"正文未能定位必须覆盖节点：{item}"[:240],
                    "evidenceSource": "outline",
                    "conflictsWith": "章节合同 must_cover_nodes",
                    "suggestion": f"在不改动既有事实的前提下兑现节点：{item}",
                }
            )

    for name, pattern, threshold in ANTI_AI_PATTERNS:
        matches = list(pattern.finditer(text))
        if len(matches) < threshold:
            continue
        quote = matches[0].group(0)
        issues.append(
            {
                "severity": "minor" if len(matches) < threshold * 2 else "major",
                "type": f"AI 痕迹/{name}",
                "evidence": f"同类表达出现 {len(matches)} 次",
                "evidenceQuote": quote,
                "evidenceSource": "content",
                "conflictsWith": "CKSKILL Anti-AI 表达检查",
                "suggestion": "保留事实与情绪变化，改用具体动作、感官或后果表达。",
            }
        )

    paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    if len(paragraphs) >= 6:
        starters = [re.sub(r"[「『\"'“‘].*", "", item[:8])[:4] for item in paragraphs]
        starter_counts = {starter: starters.count(starter) for starter in set(starters) if starter}
        repeated_starter = max(starter_counts, key=starter_counts.get) if starter_counts else ""
        if repeated_starter and starter_counts[repeated_starter] >= max(4, len(paragraphs) // 2):
            issues.append(
                {
                    "severity": "minor",
                    "type": "AI 痕迹/段落同构",
                    "evidence": f"{starter_counts[repeated_starter]} 个段落使用相近起句",
                    "evidenceQuote": next((p for p in paragraphs if p.startswith(repeated_starter)), "")[:120],
                    "evidenceSource": "content",
                    "conflictsWith": "段落节奏需要自然变化",
                    "suggestion": "按动作、对白、感官、环境反馈交替组织段落入口。",
                }
            )

    narrative_sentences = [
        sentence.strip()
        for sentence in re.split(r"[。！？!?]+", re.sub(r"[「『“][^」』”]*[」』”]", "", text))
        if sentence.strip()
    ]
    short_run = 0
    max_short_run = 0
    first_short = ""
    for sentence in narrative_sentences:
        visible = len(re.sub(r"\s+", "", sentence))
        if visible <= 12:
            short_run += 1
            max_short_run = max(max_short_run, short_run)
            if not first_short:
                first_short = sentence[:120]
        else:
            short_run = 0
    if max_short_run >= 8:
        issues.append(
            {
                "severity": "minor" if max_short_run < 12 else "major",
                "type": "AI 痕迹/连续碎句",
                "evidence": f"连续 {max_short_run} 个短叙述句",
                "evidenceQuote": first_short,
                "evidenceSource": "content",
                "conflictsWith": "CKSKILL 要求句群有自然呼吸与长短变化",
                "suggestion": "合并同一动作链的碎句，补回必要连接、现场反馈与因果承接。",
            }
        )

    narrative_paragraphs = [
        item for item in paragraphs if not re.match(r"^(?:#|>|[-*+]\s|\d+[.)]\s)", item)
    ]
    if len(text) >= 1200 and len(narrative_paragraphs) >= 12:
        short_paragraphs = [item for item in narrative_paragraphs if len(re.sub(r"\s+", "", item)) <= 24]
        short_ratio = len(short_paragraphs) / len(narrative_paragraphs)
        if short_ratio >= 0.7:
            issues.append(
                {
                    "severity": "minor",
                    "type": "AI 痕迹/过度精炼短段",
                    "evidence": f"{len(short_paragraphs)} / {len(narrative_paragraphs)} 个叙述段不超过 24 字",
                    "evidenceQuote": short_paragraphs[0][:120] if short_paragraphs else "",
                    "evidenceSource": "content",
                    "conflictsWith": "CKSKILL 去提纲化与低连接密度检查",
                    "suggestion": "只在断裂处补足动作到结果的承接，不为凑长度机械注水。",
                }
            )

    rule_by_type = {
        "正文占位符": "CK-VALIDATE-PLACEHOLDER",
        "工程信息泄漏": "CK-WRITE-OUTPUT-ONLY",
        "结构节点未兑现": "CK-PLAN-CHAPTER-CONTRACT",
    }
    for issue in issues:
        issue_type = str(issue.get("type") or "")
        quote = str(issue.get("evidenceQuote") or "")
        source = str(issue.get("evidenceSource") or "context")
        start = text.find(quote) if quote and source == "content" else -1
        issue.setdefault(
            "ruleId",
            rule_by_type.get(
                issue_type,
                "CK-DESLOP-PROSE-TICS" if issue_type.startswith("AI 痕迹/") else "CK-REVIEW-BLOCKING-DECISION",
            ),
        )
        issue.setdefault("blocking", issue.get("severity") == "fatal")
        issue.setdefault("confidence", 1.0 if issue.get("severity") == "fatal" else 0.9)
        issue.setdefault(
            "location",
            {
                "source": source,
                "start": start if start >= 0 else None,
                "end": start + len(quote) if start >= 0 else None,
                "quote": quote,
            },
        )
    return issues
