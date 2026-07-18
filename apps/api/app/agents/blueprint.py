from __future__ import annotations

import json
import re
from typing import Any

from ..models import ModelConfig
from .models import build_chat_model, close_chat_model
from .runtime import extract_text, parse_json_object, run_async


BLUEPRINT_SYSTEM = """你是 Nove 的 Story Blueprint Agent，为长篇中文网络小说搭建"故事蓝图"。
故事蓝图是全书的顶层骨架，之后的分卷规划、分章细纲都会以它为准绳。
只输出 JSON，不要解释。

schema:
{
  "book_title": "贴合故事卖点的中文书名，不加书名号",
  "genre": "最适合本故事的主类型，只写一个常见中文题材名",
  "logline": "一句话卖点（30 字内，点明主角+核心张力+爽感方向）",
  "theme": "故事主题/内核（一句话）",
  "tone": "整体基调（如：热血爽文 / 悬疑压抑 / 轻松诙谐）",
  "tags": ["题材标签", "如：系统流", "打脸", "无敌流"],
  "protagonist": {
    "name": "主角名",
    "identity": "初始身份/处境",
    "goal": "贯穿全书的核心目标",
    "motivation": "驱动其行动的深层动机",
    "flaw_or_start": "起点的弱点或困境",
    "golden_finger": "金手指/外挂/独特优势（网文核心，可为特殊能力、系统、传承等）",
    "golden_finger_cost": "不可逆代价或明确边界"
  },
  "antagonist": "主要对立面/反派势力（一句话，可以是人、组织或环境）",
  "core_conflict": "贯穿全书的核心矛盾（一句话）",
  "world": {
    "setting": "世界观核心设定（一句话）",
    "power_system": "力量体系/等级阶梯（若适用，简述递进阶梯）",
    "rules": ["关键世界规则1", "关键世界规则2"]
  },
  "satisfaction_loop": "爽点循环模式（如：受辱/危机 → 觉醒/获得 → 反击/打脸 → 获得资源/地位提升），一句话概括本书的爽感节拍",
  "reader_hooks": ["读者留存钩子1（能持续追读的悬念/期待）", "钩子2"],
  "opening_hook": "开篇 3 章内的强钩子（一句话，点明开场如何抓人）",
  "reader_contract": {
    "target_audience": "目标读者",
    "platform": "目标平台",
    "core_promise": "持续向读者兑现的核心体验"
  },
  "creative_constraints": {
    "anti_trope": "反套路约束",
    "hard_constraints": ["至少两条可验证硬约束"],
    "antagonist_mirror": "反派与主角的镜像冲突",
    "do_not_copy": ["参考作品中不可直接复制的角色、设定或剧情事实"]
  },
  "arcs_outline": ["全书阶段梗概1（对应第一卷阶段）", "阶段梗概2", "阶段梗概3"]
}

规则：
1. 贴合给定 genre / coreIdea / 篇幅；篇幅越长，arcs_outline 阶段越多（每阶段约对应一卷）。book_title 要具体、有辨识度，不使用“未命名小说”等占位词。
2. logline 必须点明"谁 + 想要什么 + 最大障碍 + 爽感方向"。
3. golden_finger 是网文留存关键：必须具体、可成长、能制造爽点，避免空泛。
4. satisfaction_loop 要写出可复用的节拍循环，后续每卷每章都按此循环设计爽点。
5. 力量体系若适用须给出清晰递进阶梯（主角可沿阶梯升级），便于后续规划实力线。
6. arcs_outline 各阶段要有递进：主角处境/实力/目标层层升级，不可原地打转。
7. 全部字段尽量非空；不确定的用合理推断填充，不要留占位符。
8. novel.writingProfile 是作者确认的创作宪法，不得被合理推断覆盖；hard_constraints 必须原样保留并贯穿后续分卷。
9. 金手指必须有代价或边界；主角缺陷必须会造成可见后果；反派要与主角形成价值或方法上的镜像冲突。
10. 只提炼参考模式，不复制参考作品的专有角色、组织、地点、能力名称或剧情事实。
"""


class AgentScopeBlueprintAgent:
    def __init__(self, config: ModelConfig):
        self.config = config
        self.name = config.name

    def generate(
        self,
        *,
        novel: dict[str, Any],
        volume_hint: int = 1,
    ) -> dict[str, Any]:
        return run_async(self._generate_async(novel=novel, volume_hint=volume_hint))

    async def _generate_async(
        self,
        *,
        novel: dict[str, Any],
        volume_hint: int,
    ) -> dict[str, Any]:
        from agentscope.agent import Agent, ReActConfig
        from agentscope.message import UserMsg

        model = build_chat_model(self.config, stream=False)
        try:
            if getattr(model, "parameters", None) is not None:
                model.parameters.temperature = 0.6

            agent = Agent(
                name="Blueprint",
                system_prompt=BLUEPRINT_SYSTEM,
                model=model,
                toolkit=None,
                react_config=ReActConfig(max_iters=1),
            )
            payload = {
                "novel": novel,
                "suggestedVolumes": max(1, volume_hint),
            }
            reply = await agent.reply(
                UserMsg(
                    name="nove",
                    content="请生成故事蓝图，只返回 JSON：\n"
                    + json.dumps(payload, ensure_ascii=False),
                )
            )
            data = parse_json_object(extract_text(reply))
            return normalize_blueprint(data)
        finally:
            await close_chat_model(model)


def suggested_volume_count(planned_chapters: int) -> int:
    """Rough volume count from planned chapters (约 40-80 章/卷)。"""
    chapters = max(1, int(planned_chapters or 80))
    if chapters <= 60:
        return 1
    return max(1, min(12, round(chapters / 60)))


def heuristic_blueprint(novel: dict[str, Any]) -> dict[str, Any]:
    """Offline fallback blueprint derived from the core idea."""
    idea = str(novel.get("coreIdea") or novel.get("title") or "主角在异世界逆袭").strip()
    title = str(novel.get("title") or "本书").strip()
    genre = str(novel.get("genre") or "玄幻").strip()
    if genre in {"", "未分类", "让 AI 判断"}:
        keyword_genres = (
            (("案件", "证词", "凶手", "失踪", "死亡", "秘密"), "悬疑"),
            (("修仙", "宗门", "飞升", "灵根", "仙人"), "仙侠"),
            (("星际", "飞船", "机器人", "人工智能", "未来"), "科幻"),
            (("王朝", "皇帝", "将军", "战国", "古代"), "历史"),
            (("恋爱", "婚姻", "前任", "心动", "暗恋"), "现代言情"),
            (("异能", "都市", "公司", "医生", "警察"), "都市"),
        )
        genre = next(
            (candidate for keywords, candidate in keyword_genres if any(word in idea for word in keywords)),
            "玄幻",
        )
    planned = int(novel.get("plannedChapters") or 80)
    volumes = suggested_volume_count(planned)
    profile = novel.get("writingProfile") if isinstance(novel.get("writingProfile"), dict) else {}
    default_names = {
        "玄幻": "林渊",
        "仙侠": "沈砚",
        "都市": "顾言",
        "悬疑": "周既明",
        "科幻": "陆星野",
        "历史": "谢临川",
        "古代言情": "苏令仪",
        "现代言情": "许知微",
    }
    protagonist_name = str(profile.get("protagonist_name") or default_names.get(genre, "林川"))
    protagonist_desire = str(profile.get("protagonist_desire") or f"实现「{idea}」")
    protagonist_flaw = str(profile.get("protagonist_flaw") or "起点实力弱、资源匮乏")
    golden_finger = str(profile.get("golden_finger") or "一件能持续成长的独特外挂")
    arcs = [f"第 {i + 1} 阶段：围绕「{idea}」层层升级" for i in range(volumes)]
    fragment = re.split(r"[。！？；，,]", idea, maxsplit=1)[0].strip()
    generated_title = fragment[:16] if 3 <= len(fragment) <= 16 else f"{genre}：{fragment[:10]}"
    if title and title not in {"未命名小说", "未命名", "Untitled"}:
        generated_title = title
    return normalize_blueprint(
        {
            "book_title": generated_title or f"{genre}新章",
            "genre": genre,
            "logline": f"{idea}"[:30],
            "theme": f"围绕「{idea}」的成长与抉择",
            "tone": "热血爽文",
            "tags": [genre, "成长", "逆袭"],
            "protagonist": {
                "name": protagonist_name,
                "identity": "起点低微的普通人",
                "goal": protagonist_desire,
                "motivation": "改变自身处境、守护重要之人",
                "flaw_or_start": protagonist_flaw,
                "golden_finger": golden_finger,
                "golden_finger_cost": str(profile.get("golden_finger_cost") or "能力使用受资源和后果限制"),
            },
            "antagonist": "压制主角的旧秩序与强敌",
            "core_conflict": f"主角追求「{idea}」与外部压制之间的对抗",
            "world": {
                "setting": f"{genre}背景下的世界",
                "power_system": "由低到高的实力阶梯，主角逐级突破",
                "rules": ["实力提升必须消耗可追踪资源", "越级破局必须付出可见代价"],
            },
            "satisfaction_loop": "受压 → 获得机缘/变强 → 反击打脸 → 地位与资源提升",
            "reader_hooks": ["主角能否突破当前瓶颈", "外挂的真正来历"],
            "opening_hook": f"开篇即抛出「{idea}」的核心危机，主角被迫踏上逆袭之路",
            "reader_contract": {
                "target_audience": str(profile.get("target_audience") or f"喜欢{genre}强情节与成长反馈的读者"),
                "platform": str(profile.get("platform") or "番茄小说"),
                "core_promise": f"持续兑现「{idea}」带来的成长、冲突与结果反馈",
            },
            "creative_constraints": {
                "anti_trope": str(profile.get("anti_trope") or "避免无代价的模板化胜利"),
                "hard_constraints": profile.get("hard_constraints") or [
                    "关键胜利必须由已展示的能力、选择或资源促成",
                    "每卷结束必须改变主角的处境、关系或目标",
                ],
                "antagonist_mirror": str(profile.get("antagonist_mirror") or "反派以相反方法追求相似目标"),
                "do_not_copy": [],
            },
            "arcs_outline": arcs,
        }
    )


def _str(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _str_list(value: Any, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    out = [str(x).strip() for x in value if str(x).strip()]
    return out[:limit]


def normalize_blueprint(data: dict[str, Any]) -> dict[str, Any]:
    data = data if isinstance(data, dict) else {}
    proto = data.get("protagonist") if isinstance(data.get("protagonist"), dict) else {}
    world = data.get("world") if isinstance(data.get("world"), dict) else {}
    reader_contract = data.get("reader_contract") if isinstance(data.get("reader_contract"), dict) else {}
    constraints = data.get("creative_constraints") if isinstance(data.get("creative_constraints"), dict) else {}
    return {
        "book_title": _str(data.get("book_title")),
        "genre": _str(data.get("genre")),
        "logline": _str(data.get("logline")),
        "theme": _str(data.get("theme")),
        "tone": _str(data.get("tone")),
        "tags": _str_list(data.get("tags"), 10),
        "protagonist": {
            "name": _str(proto.get("name")),
            "identity": _str(proto.get("identity")),
            "goal": _str(proto.get("goal")),
            "motivation": _str(proto.get("motivation")),
            "flaw_or_start": _str(proto.get("flaw_or_start")),
            "golden_finger": _str(proto.get("golden_finger")),
            "golden_finger_cost": _str(proto.get("golden_finger_cost")),
        },
        "antagonist": _str(data.get("antagonist")),
        "core_conflict": _str(data.get("core_conflict")),
        "world": {
            "setting": _str(world.get("setting")),
            "power_system": _str(world.get("power_system")),
            "rules": _str_list(world.get("rules"), 15),
        },
        "satisfaction_loop": _str(data.get("satisfaction_loop")),
        "reader_hooks": _str_list(data.get("reader_hooks"), 8),
        "opening_hook": _str(data.get("opening_hook")),
        "reader_contract": {
            "target_audience": _str(reader_contract.get("target_audience")),
            "platform": _str(reader_contract.get("platform")),
            "core_promise": _str(reader_contract.get("core_promise")),
        },
        "creative_constraints": {
            "anti_trope": _str(constraints.get("anti_trope")),
            "hard_constraints": _str_list(constraints.get("hard_constraints"), 12),
            "antagonist_mirror": _str(constraints.get("antagonist_mirror")),
            "do_not_copy": _str_list(constraints.get("do_not_copy"), 20),
        },
        "arcs_outline": _str_list(data.get("arcs_outline"), 20),
    }
