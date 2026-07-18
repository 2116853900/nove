from __future__ import annotations

import asyncio
import json
import re
from typing import Any


def run_async(coro: Any) -> Any:
    """Run an async coroutine from sync FastAPI background tasks."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    # Nested loop (tests / unexpected): use a dedicated loop on a thread.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def extract_text(payload: Any) -> str:
    """Pull plain text from AgentScope Msg / ChatResponse / blocks."""
    if payload is None:
        return ""
    if isinstance(payload, str):
        return payload.strip()

    content = getattr(payload, "content", payload)
    if isinstance(content, str):
        return content.strip()

    parts: list[str] = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                parts.append(block)
                continue
            text = getattr(block, "text", None)
            if text:
                parts.append(str(text))
                continue
            if isinstance(block, dict):
                if block.get("text"):
                    parts.append(str(block["text"]))
                elif block.get("type") == "text" and block.get("content"):
                    parts.append(str(block["content"]))
    return "\n".join(parts).strip()


def parse_json_object(text: str) -> dict[str, Any]:
    """Best-effort JSON object extraction from model output."""
    raw = (text or "").strip()
    if not raw:
        raise ValueError("empty model output")

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, re.IGNORECASE)
    if fence:
        raw = fence.group(1).strip()

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        data = json.loads(raw[start : end + 1])
        if isinstance(data, dict):
            return data
    raise ValueError("model output is not a JSON object")
