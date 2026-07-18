from __future__ import annotations

import json
from typing import Any, Callable

from ..models import ModelConfig
from ..observability import summarize_json, track_agent_call
from .models import build_chat_model, close_chat_model
from .runtime import extract_text, run_async


WRITER_SYSTEM = """你是 Nove 的长篇小说 Writer Agent。
硬约束：
1. 严格按任务书顺序执行：本章硬性约束 → CBN/CPNs/CEN 与必须节点 → 本章禁区 → 风格指引 → 动态上下文。
2. 权威事实、时间锚点、禁止事件、锁定原文不可违背；动态上下文只能补充，不能覆盖前四层。
3. 围绕 CBN 开局、按顺序推进 CPN、以 CEN 落实变化；必须覆盖节点必须在正文中可定位。
4. 只输出章节正文，不解释过程、不输出 JSON 或工程字段；标题使用 Markdown 标题结构。
5. 必须写出目标、阻力、选择、代价和后果，不以旁白概括代替关键场面。
6. 避免模板化排比、意义总结、同构段落、机械转折和空泛认知句；去 AI 只改表达，不改故事事实。
7. 若存在 must_preserve，必须原样保留这些片段；不得提前揭示 forbidden_zones。
"""


class AgentScopeWriter:
    """Chapter writer backed by AgentScope OpenAI-compatible models."""

    def __init__(self, config: ModelConfig, session=None, *, novel_id: str = "", chapter_id: str | None = None):
        self.config = config
        self.name = config.name
        self.session = session
        self.novel_id = novel_id
        self.chapter_id = chapter_id

    def generate(
        self,
        *,
        title: str,
        brief: dict[str, Any],
        existing_content: str,
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        with track_agent_call(
            self.session,
            novel_id=self.novel_id,
            chapter_id=self.chapter_id,
            agent_name="Writer",
            model_name=self.name,
            operation="generate",
            input_summary=title,
        ) as meta:
            text = run_async(
                self._generate_async(
                    title=title,
                    brief=brief,
                    existing_content=existing_content,
                    on_delta=on_delta,
                )
            )
            meta["output_summary"] = text[:200]
            return text

    async def _generate_async(
        self,
        *,
        title: str,
        brief: dict[str, Any],
        existing_content: str,
        on_delta: Callable[[str], None] | None = None,
    ) -> str:
        from agentscope.agent import Agent, ReActConfig
        from agentscope.event import TextBlockDeltaEvent
        from agentscope.message import UserMsg

        model = build_chat_model(self.config, stream=on_delta is not None)
        try:
            agent = Agent(
                name="Writer",
                system_prompt=WRITER_SYSTEM,
                model=model,
                toolkit=None,
                react_config=ReActConfig(max_iters=1),
            )

            context = brief.get("_context") or {}
            contract = context.get("writingContract") or {}
            authoritative_context = {
                key: value for key, value in context.items() if key != "writingContract"
            }
            task = {key: value for key, value in brief.items() if key != "_context"}
            payload = {
                "chapterTitle": title,
                "chapterTask": task,
                "writingTaskbook": contract.get("taskbook") or {},
                "taskbookOrder": contract.get("taskbookOrder") or [],
                "authoritativeContext": authoritative_context,
                "sceneBeats": brief.get("_plot_plan") or {},
                "existingContent": existing_content or "",
                "instructions": {
                    "mustPreserve": task.get("must_preserve") or [],
                    "mustImprove": task.get("must_improve") or [],
                    "mustNotInclude": task.get("forbidden_events") or [],
                    "targetWords": task.get("target_words"),
                    "pace": task.get("pace"),
                    "dialogueRatio": task.get("dialogue_ratio"),
                    "styleInstruction": task.get("style_instruction") or "",
                },
            }
            user = UserMsg(
                name="nove",
                content=(
                    "请根据以下任务生成或改写章节正文。\n"
                    + json.dumps(payload, ensure_ascii=False, indent=2)
                ),
            )
            if on_delta is None:
                reply = await agent.reply(user)
                text = extract_text(reply)
            else:
                parts: list[str] = []
                async for event in agent.reply_stream(user):
                    if isinstance(event, TextBlockDeltaEvent) and event.delta:
                        parts.append(event.delta)
                        on_delta(event.delta)
                text = "".join(parts).strip()
            if not text:
                raise ValueError("Writer Agent 没有返回可用正文")
            return text
        finally:
            await close_chat_model(model)
