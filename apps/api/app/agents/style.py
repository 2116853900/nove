from __future__ import annotations

import json
from typing import Any

from ..models import ModelConfig
from .models import build_chat_model, close_chat_model
from .runtime import extract_text, run_async


OPS = {
    "expand": "扩写：在保持原意的前提下增加细节、动作与感官描写，篇幅明显变长。",
    "shrink": "缩写：压缩冗余，保留关键信息与语气，篇幅明显变短。",
    "rewrite": "改写：换表达方式重写，不改变事实与人物立场。",
    "dialogue": "对话优化：让对话更自然、更符合人物口吻，保留剧情信息。",
    "style": "文风优化：贴合作者文风与小说设定，减少模板化 AI 痕迹。",
}


STYLE_SYSTEM = """你是 Nove 的 Style Agent，负责对选中的正文片段做局部改写。
硬约束：
1. 只输出改写后的选区正文，不要解释，不要加引号外壳。
2. 不得改变锁定事实、人物生死与已确认设定。
3. 不得引入后续剧情剧透。
4. 尽量保持与前后文衔接自然。
5. instruction 非空时，必须优先解决 instruction 指出的问题，不能只做同义替换。
"""


class AgentScopeStyleAgent:
    def __init__(self, config: ModelConfig):
        self.config = config
        self.name = config.name

    def edit_selection(
        self,
        *,
        operation: str,
        selected_text: str,
        before: str,
        after: str,
        instruction: str,
        context: dict[str, Any],
    ) -> str:
        return run_async(
            self._edit_async(
                operation=operation,
                selected_text=selected_text,
                before=before,
                after=after,
                instruction=instruction,
                context=context,
            )
        )

    async def _edit_async(
        self,
        *,
        operation: str,
        selected_text: str,
        before: str,
        after: str,
        instruction: str,
        context: dict[str, Any],
    ) -> str:
        from agentscope.agent import Agent, ReActConfig
        from agentscope.message import UserMsg

        model = build_chat_model(self.config, stream=False)
        try:
            if getattr(model, "parameters", None) is not None:
                model.parameters.temperature = 0.5

            agent = Agent(
                name="Style",
                system_prompt=STYLE_SYSTEM,
                model=model,
                toolkit=None,
                react_config=ReActConfig(max_iters=1),
            )
            op_desc = OPS.get(operation, OPS["rewrite"])
            payload = {
                "operation": operation,
                "operationGuide": op_desc,
                "instruction": instruction,
                "selectedText": selected_text,
                "beforeContext": before[-800:],
                "afterContext": after[:800],
                "authoritativeContext": {
                    "novel": context.get("novel"),
                    "rules": context.get("rules"),
                    "entities": context.get("entities"),
                },
            }
            reply = await agent.reply(
                UserMsg(
                    name="nove",
                    content="请严格遵循 instruction 改写选区，只返回改写后的正文：\n"
                    + json.dumps(payload, ensure_ascii=False),
                )
            )
            text = extract_text(reply).strip()
            if not text:
                raise ValueError("Style Agent 没有返回可用正文")
            return text
        finally:
            await close_chat_model(model)


def heuristic_selection_edit(
    *,
    operation: str,
    selected_text: str,
    instruction: str = "",
) -> str:
    text = selected_text.strip()
    if not text:
        return text
    note = f"（{instruction}）" if instruction else ""
    if operation == "expand":
        return (
            f"{text}\n\n"
            f"他停了一停，把刚才没说清的细节补全：空气里有细微的变化，"
            f"脚步声、光线和呼吸都被重新写进这一刻{note}。"
        )
    if operation == "shrink":
        first = text.split("。")[0]
        return (first + "。") if first else text[: max(20, len(text) // 3)]
    if operation == "dialogue":
        cleaned = text.strip().strip("「」\"'")
        return f"「{cleaned}」{note}"
    if operation == "style":
        return f"{text.rstrip('。')}——语气更克制，意象更具体{note}。"
    # rewrite default
    return f"{text.rstrip('。')}{note}。局面没有变轻松，但说法已经不同。"
