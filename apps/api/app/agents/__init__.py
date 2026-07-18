"""AgentScope-backed writing / audit agents for Nove."""

from .auditor import AgentScopeAuditor
from .memory_agent import AgentScopeMemoryAgent
from .models import build_chat_model, model_config_for_role
from .outline import AgentScopeOutlineAgent, heuristic_outline_children
from .plot import AgentScopePlotAgent
from .skills_runtime import SkillRuntime, ensure_default_skills
from .style import AgentScopeStyleAgent, heuristic_selection_edit
from .workflow import extract_memory_delta, plan_scene_beats, run_continuity_skill
from .writer import AgentScopeWriter

__all__ = [
    "AgentScopeAuditor",
    "AgentScopeMemoryAgent",
    "AgentScopeOutlineAgent",
    "AgentScopePlotAgent",
    "AgentScopeStyleAgent",
    "AgentScopeWriter",
    "SkillRuntime",
    "build_chat_model",
    "ensure_default_skills",
    "extract_memory_delta",
    "heuristic_outline_children",
    "heuristic_selection_edit",
    "model_config_for_role",
    "plan_scene_beats",
    "run_continuity_skill",
]
