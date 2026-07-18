from __future__ import annotations

from typing import Any

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from ..models import ModelConfig, Novel
from ..security import decrypt_secret


def model_config_for_role(session: Session, novel_id: str, role: str) -> ModelConfig | None:
    novel = session.get(Novel, novel_id)
    workspace_id = novel.workspace_id if novel is not None else None
    configs = session.scalars(
        select(ModelConfig)
        .where(
            ModelConfig.status == "connected",
            or_(
                ModelConfig.novel_id == novel_id,
                ModelConfig.novel_id.is_(None),
            ),
        )
        .order_by(
            case((ModelConfig.novel_id == novel_id, 0), else_=1),
            ModelConfig.is_default.desc(),
            ModelConfig.updated_at.desc(),
        )
    ).all()
    for config in configs:
        if config.novel_id is None and workspace_id and config.workspace_id != workspace_id:
            continue
        roles = config.roles or []
        if (role in roles or (config.novel_id is None and not roles)) and config.provider not in {
            "本地",
            "local",
            "Ollama",
            "vLLM",
        }:
            return config
    return None


def is_local_provider(config: ModelConfig | None) -> bool:
    if config is None:
        return True
    return config.provider in {"本地", "local"}


def build_chat_model(config: ModelConfig, *, stream: bool = False) -> Any:
    """Build an AgentScope 2.x OpenAI-compatible chat model from Nove ModelConfig."""
    import openai
    from agentscope.credential import OpenAICredential
    from agentscope.model import OpenAIChatModel

    if not config.base_url:
        raise ValueError(f"模型 {config.name} 未配置 Base URL")

    api_key = decrypt_secret(config.encrypted_api_key) or "nove-local-key"
    credential = OpenAICredential(
        api_key=api_key,
        base_url=config.base_url.rstrip("/"),
    )
    top_p = getattr(config, "top_p", 100) or 100
    timeout_ms = getattr(config, "timeout_ms", 120000) or 120000
    context_size = getattr(config, "context_size", 128000) or 128000
    extra_body = getattr(config, "extra_body", None) or {}
    timeout_s = max(1.0, float(timeout_ms) / 1000.0)
    parameters = OpenAIChatModel.Parameters(
        temperature=max(0.0, min(2.0, float(config.temperature) / 100.0)),
        top_p=max(0.01, min(1.0, float(top_p) / 100.0)),
        max_tokens=max(256, int(config.max_output_tokens or 4096)),
    )
    http_client = openai.DefaultAsyncHttpxClient(timeout=timeout_s)
    model = OpenAIChatModel(
        credential=credential,
        model=config.model_id,
        parameters=parameters,
        stream=stream,
        max_retries=2,
        context_size=max(1024, int(context_size)),
        client_kwargs={"http_client": http_client, "timeout": timeout_s},
        extra_body=extra_body or None,
    )
    model._nove_http_client = http_client
    return model


async def close_chat_model(model: Any) -> None:
    """Close the HTTP client on the event loop that used the chat model."""
    http_client = getattr(model, "_nove_http_client", None)
    if http_client is None:
        return
    model._nove_http_client = None
    await http_client.aclose()
