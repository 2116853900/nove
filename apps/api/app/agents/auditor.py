from __future__ import annotations

import json
import hashlib
import re
from difflib import SequenceMatcher
from typing import Any

from ..models import ModelConfig
from .models import build_chat_model, close_chat_model
from .runtime import extract_text, parse_json_object, run_async


AUDITOR_SYSTEM = """你是 Nove 的独立 Auditor Agent。
你不负责重写正文，只输出严格 JSON（不要 Markdown 围栏外的说明）。

评分维度（默认，实际以请求 dimensions 为准）：
- 连续性 max 18
- 人物一致性 max 12
- 大纲完成度 max 15
- 时间线 max 10
- 剧情推进 max 10
- 冲突张力 max 10
- 亮点与转折 max 10
- 文笔质量 max 8
- AI 痕迹 max 7

规则：
1. 每个扣分项优先引用正文 evidenceQuote：必须从 content 中逐字复制一段连续原文，不得概括、拼接或改写。
   如果问题属于“缺失内容”且没有可引用正文，evidenceQuote 返回空字符串，evidenceSource 写 outline 或 context。
2. 致命问题 severity 用 "fatal"：死亡人物复活、知识泄漏、锁定内容被删、缺失必达事件且不可补救、违反锁定世界规则。
3. major / minor 用于非致命问题。
4. decision 只能是 PASS / REVISE / REWRITE。
5. total_score 为 0-100 整数。
6. 对连续性、人物、章纲/结构节点、时间线、剧情推进、冲突与代价、亮点/钩子、文笔、AI 痕迹逐项给出明确结果；不能用总评代替单项检查。
7. must_cover_nodes、forbidden_zones、时间锚点、锁定事实属于合同门禁；缺失或违反时必须列出问题。
8. 低置信判断必须说明证据不足，不得编造正文、设定或上下文中的证据。

输出 schema：
{
  "total_score": 0,
  "decision": "PASS|REVISE|REWRITE",
  "dimension_scores": [{"name":"连续性","score":18,"max":20}],
  "fatal_issues": [],
  "issues": [
    {
      "severity": "fatal|major|minor",
      "type": "问题类型",
      "evidence": "问题依据的简短说明",
      "evidenceQuote": "从正文逐字复制的连续原句；无法引用时为空",
      "evidenceSource": "content|outline|context",
      "conflictsWith": "冲突依据",
      "suggestion": "修改建议"
    }
  ],
  "strengths": ["优点"],
  "rewrite_requirements": {
    "mustPreserve": [],
    "mustImprove": [],
    "mustNotInclude": []
  }
}
"""


class AgentScopeAuditor:
    """LLM auditor via AgentScope; returns a normalized audit dict."""

    def __init__(self, config: ModelConfig):
        self.config = config
        self.name = config.name

    def audit(
        self,
        *,
        title: str,
        content: str,
        brief: dict[str, Any],
        context: dict[str, Any],
        dimensions: list[dict[str, Any]],
        protected_texts: list[str],
        pass_score: int,
        revise_score: int,
    ) -> dict[str, Any]:
        return run_async(
            self._audit_async(
                title=title,
                content=content,
                brief=brief,
                context=context,
                dimensions=dimensions,
                protected_texts=protected_texts,
                pass_score=pass_score,
                revise_score=revise_score,
            )
        )

    async def _audit_async(
        self,
        *,
        title: str,
        content: str,
        brief: dict[str, Any],
        context: dict[str, Any],
        dimensions: list[dict[str, Any]],
        protected_texts: list[str],
        pass_score: int,
        revise_score: int,
    ) -> dict[str, Any]:
        from agentscope.agent import Agent, ReActConfig
        from agentscope.message import UserMsg

        # Force low temperature for audit stability.
        model = build_chat_model(self.config, stream=False)
        try:
            if getattr(model, "parameters", None) is not None:
                model.parameters.temperature = 0.1

            agent = Agent(
                name="Auditor",
                system_prompt=AUDITOR_SYSTEM,
                model=model,
                toolkit=None,
                react_config=ReActConfig(max_iters=1),
            )
            payload = {
                "chapterTitle": title,
                "content": content,
                "chapterBrief": brief,
                "authoritativeContext": context,
                "dimensions": dimensions,
                "protectedTexts": protected_texts,
                "thresholds": {
                    "passScore": pass_score,
                    "reviseScore": revise_score,
                },
            }
            user = UserMsg(
                name="nove",
                content="请审计以下章节并只返回 JSON：\n"
                + json.dumps(payload, ensure_ascii=False),
            )
            reply = await agent.reply(user)
            data = parse_json_object(extract_text(reply))
            return normalize_audit_result(
                data,
                content=content,
                dimensions=dimensions,
                protected_texts=protected_texts,
                brief=brief,
                pass_score=pass_score,
                revise_score=revise_score,
            )
        finally:
            await close_chat_model(model)


def normalize_audit_result(
    data: dict[str, Any],
    *,
    content: str = "",
    dimensions: list[dict[str, Any]],
    protected_texts: list[str],
    brief: dict[str, Any],
    pass_score: int,
    revise_score: int,
) -> dict[str, Any]:
    issues = []
    for item in data.get("issues") or []:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "minor").lower()
        if severity not in {"fatal", "major", "minor"}:
            severity = "minor"
        issues.append(
            attach_evidence_metadata(
                {
                "severity": severity,
                "type": str(item.get("type") or "审计问题"),
                "evidence": str(item.get("evidence") or "")[:240],
                "evidenceQuote": str(item.get("evidenceQuote") or "")[:240],
                "evidenceSource": str(item.get("evidenceSource") or ""),
                "conflictsWith": str(item.get("conflictsWith") or item.get("reason") or ""),
                "suggestion": str(item.get("suggestion") or item.get("revision_instruction") or ""),
                },
                content,
            )
        )

    dim_scores = []
    raw_dims = data.get("dimension_scores") or []
    if isinstance(raw_dims, list) and raw_dims:
        for item in raw_dims:
            if not isinstance(item, dict):
                continue
            maximum = int(item.get("max") or 10)
            score = int(item.get("score") if item.get("score") is not None else maximum)
            dim_scores.append(
                {
                    "name": str(item.get("name") or "维度"),
                    "score": max(0, min(maximum, score)),
                    "max": maximum,
                }
            )
    else:
        for item in dimensions:
            maximum = int(item.get("max") or 10)
            dim_scores.append({"name": item.get("name") or "维度", "score": maximum, "max": maximum})

    total = data.get("total_score")
    if total is None:
        total = sum(int(d["score"]) for d in dim_scores)
    total = max(0, min(100, int(total)))

    fatal = [i for i in issues if i["severity"] == "fatal"]
    for item in data.get("fatal_issues") or []:
        if isinstance(item, dict):
            fatal.append(
                attach_evidence_metadata(
                    {
                    "severity": "fatal",
                    "type": str(item.get("type") or "致命问题"),
                    "evidence": str(item.get("evidence") or "")[:240],
                    "evidenceQuote": str(item.get("evidenceQuote") or "")[:240],
                    "evidenceSource": str(item.get("evidenceSource") or ""),
                    "conflictsWith": str(item.get("conflictsWith") or ""),
                    "suggestion": str(item.get("suggestion") or ""),
                    },
                    content,
                )
            )
            issues.append(fatal[-1])

    decision = str(data.get("decision") or "").upper()
    if decision not in {"PASS", "REVISE", "REWRITE"}:
        if fatal:
            decision = "REWRITE"
        elif total >= pass_score:
            decision = "PASS"
        elif total >= revise_score:
            decision = "REVISE"
        else:
            decision = "REWRITE"

    rewrite = data.get("rewrite_requirements") if isinstance(data.get("rewrite_requirements"), dict) else {}
    return {
        "total_score": total,
        "decision": decision,
        "dimension_scores": dim_scores,
        "fatal_issues": [i for i in issues if i["severity"] == "fatal"],
        "issues": issues,
        "strengths": [str(s) for s in (data.get("strengths") or [])][:8],
        "rewrite_requirements": {
            "mustPreserve": list(rewrite.get("mustPreserve") or brief.get("must_preserve") or protected_texts),
            "mustImprove": list(rewrite.get("mustImprove") or [i["suggestion"] for i in issues if i.get("suggestion")]),
            "mustNotInclude": list(rewrite.get("mustNotInclude") or brief.get("forbidden_events") or []),
        },
        "model_name": data.get("model_name"),
    }


def attach_evidence_metadata(
    issue: dict[str, Any], content: str
) -> dict[str, Any]:
    result = dict(issue)
    explanation = str(result.get("evidence") or "").strip()
    requested_quote = str(result.get("evidenceQuote") or "").strip()
    quote = _exact_content_quote(content, requested_quote or explanation)
    if quote:
        result["evidenceQuote"] = quote[:240]
        result["evidenceSource"] = "content"
        result["locatable"] = True
    else:
        source = str(result.get("evidenceSource") or "").lower()
        result["evidenceQuote"] = ""
        result["evidenceSource"] = source if source in {"outline", "context"} else "context"
        result["locatable"] = False
    severity = str(result.get("severity") or "minor").lower()
    issue_type = str(result.get("type") or "审计问题")
    known_rule_ids = {
        "正文占位符": "CK-VALIDATE-PLACEHOLDER",
        "工程信息泄漏": "CK-WRITE-OUTPUT-ONLY",
        "结构节点未兑现": "CK-PLAN-CHAPTER-CONTRACT",
        "禁止事件": "CK-PLAN-CHAPTER-CONTRACT",
        "锁定内容": "CK-WRITE-TASKBOOK-ORDER",
        "权威事实冲突": "CK-EVIDENCE-CONFIDENCE",
        "知识边界": "CK-EVIDENCE-CONFIDENCE",
    }
    if not result.get("ruleId"):
        if issue_type.startswith("AI 痕迹"):
            result["ruleId"] = "CK-DESLOP-PROSE-TICS"
        else:
            digest = hashlib.sha256(issue_type.encode("utf-8")).hexdigest()[:12].upper()
            result["ruleId"] = known_rule_ids.get(issue_type, f"NOVE-AUDIT-{digest}")
    result["blocking"] = bool(result.get("blocking", severity == "fatal"))
    try:
        confidence = float(result.get("confidence"))
    except (TypeError, ValueError):
        confidence = 0.98 if severity == "fatal" else (0.9 if result["locatable"] else 0.7)
    result["confidence"] = max(0.0, min(1.0, confidence))
    final_quote = str(result.get("evidenceQuote") or "")
    source = str(result.get("evidenceSource") or "context")
    start = content.find(final_quote) if source == "content" and final_quote else -1
    result["location"] = {
        "source": source,
        "start": start if start >= 0 else None,
        "end": start + len(final_quote) if start >= 0 else None,
        "quote": final_quote,
    }
    return result


def _exact_content_quote(content: str, evidence: str) -> str:
    raw = evidence.strip().strip("「」『』“”‘’\"'")
    if not raw or not content:
        return ""
    if raw in content:
        return raw

    quoted = re.findall(r"[「『“‘\"']([^」』”’\"']{6,160})[」』”’\"']", evidence)
    for candidate in sorted(quoted, key=len, reverse=True):
        if candidate in content:
            return candidate

    match = SequenceMatcher(None, content, raw, autojunk=False).find_longest_match()
    if match.size < 8:
        return ""
    return content[match.a : match.a + match.size].strip()
