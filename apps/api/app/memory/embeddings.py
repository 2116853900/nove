from __future__ import annotations

import hashlib
import math
import re
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ModelConfig
from ..security import decrypt_secret
from .local_catalog import get_catalog_entry, get_catalog_entry_by_model_id


class EmbeddingProvider(Protocol):
    model_id: str
    version: str

    def dimensions(self) -> int: ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


def l2_normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


class LocalHashEmbedding:
    """Deterministic bag-of-tokens embedding for offline / tests (no external API)."""

    def __init__(self, dimensions: int = 64, model_id: str = "nove-local-hash", version: str = "1"):
        self.model_id = model_id
        self.version = version
        self._dim = dimensions

    def dimensions(self) -> int:
        return self._dim

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        tokens = re.findall(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+", text.lower())
        if not tokens:
            tokens = ["empty"]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            # Two slots per token for slight smoothing.
            for offset in (0, 8):
                idx = int.from_bytes(digest[offset : offset + 4], "little") % self._dim
                sign = 1.0 if digest[offset + 4] % 2 == 0 else -1.0
                vec[idx] += sign
        return l2_normalize(vec)


class OpenAICompatibleEmbedding:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model_id: str,
        dimensions: int | None = None,
        version: str = "1",
    ):
        self.model_id = model_id
        self.version = version
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._dimensions = dimensions

    def dimensions(self) -> int:
        if self._dimensions:
            return self._dimensions
        # Probe with empty-ish string only if needed; default common size.
        sample = self.embed_query("dimension probe")
        self._dimensions = len(sample)
        return self._dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        response = httpx.post(
            f"{self._base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self.model_id, "input": texts},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        data = sorted(payload.get("data") or [], key=lambda item: item.get("index", 0))
        vectors = [list(map(float, item.get("embedding") or [])) for item in data]
        if len(vectors) != len(texts):
            raise ValueError("embedding response size mismatch")
        if vectors and self._dimensions is None:
            self._dimensions = len(vectors[0])
        return [l2_normalize(v) for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


class LocalNeuralEmbedding:
    """In-process ONNX embedding via fastembed (or test factory)."""

    def __init__(
        self,
        *,
        model_id: str,
        catalog_key: str | None = None,
        dimensions: int | None = None,
        version: str = "1",
    ):
        self.model_id = model_id
        self.version = version
        self._catalog_key = catalog_key
        self._dimensions = dimensions
        self._encoder = None

    def _ensure_encoder(self) -> Any:
        if self._encoder is None:
            from .local_runtime import load_encoder

            self._encoder = load_encoder(self.model_id, catalog_key=self._catalog_key)
        return self._encoder

    def dimensions(self) -> int:
        if self._dimensions:
            return self._dimensions
        entry = None
        if self._catalog_key:
            entry = get_catalog_entry(self._catalog_key)
        if entry is None:
            entry = get_catalog_entry_by_model_id(self.model_id)
        if entry is not None:
            self._dimensions = entry["dimensions"]
            return self._dimensions
        sample = self.embed_query("dimension probe")
        self._dimensions = len(sample)
        return self._dimensions

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        encoder = self._ensure_encoder()
        # fastembed returns a generator of numpy arrays / lists
        raw = list(encoder.embed(texts))
        vectors: list[list[float]] = []
        for item in raw:
            if hasattr(item, "tolist"):
                vectors.append([float(x) for x in item.tolist()])
            else:
                vectors.append([float(x) for x in item])
        if vectors and self._dimensions is None:
            self._dimensions = len(vectors[0])
        return [l2_normalize(v) for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        return self.embed_documents([text])[0]


_EMBEDDED_PROVIDERS = {"内嵌", "embedded", "local-neural", "local_neural"}


def _is_embedded_provider(provider: str) -> bool:
    return (provider or "").strip() in _EMBEDDED_PROVIDERS


def resolve_embedding(session: Session, novel_id: str) -> EmbeddingProvider:
    """Pick Embedding-role model for this novel.

    Supports:
    - In-process neural models (provider=内嵌, fastembed cache)
    - Any OpenAI-compatible endpoint (cloud or self-hosted HTTP)
    - Fallback: deterministic hash vectors when nothing is assigned
    """
    configs = session.scalars(
        select(ModelConfig)
        .where(ModelConfig.novel_id == novel_id, ModelConfig.status == "connected")
        .order_by(ModelConfig.updated_at.desc())
    ).all()
    for config in configs:
        roles = config.roles or []
        if "Embedding" not in roles and "embedding" not in roles:
            continue

        extra = config.extra_body or {}
        catalog_key = extra.get("catalogKey") if isinstance(extra, dict) else None
        dims = extra.get("dimensions") if isinstance(extra, dict) else None
        if isinstance(dims, str) and dims.isdigit():
            dims = int(dims)
        if not isinstance(dims, int):
            dims = None

        if _is_embedded_provider(config.provider):
            try:
                return LocalNeuralEmbedding(
                    model_id=config.model_id,
                    catalog_key=str(catalog_key) if catalog_key else None,
                    dimensions=dims,
                    version="1",
                )
            except Exception:
                continue

        # Hash-only placeholder (no remote endpoint)
        if config.provider in {"本地", "local"} and not (config.base_url or "").strip():
            return LocalHashEmbedding(model_id=config.model_id or "nove-local-hash")
        if not (config.base_url or "").strip():
            continue
        try:
            return OpenAICompatibleEmbedding(
                base_url=config.base_url,
                api_key=decrypt_secret(config.encrypted_api_key) or "nove",
                model_id=config.model_id,
                version="1",
            )
        except Exception:
            continue
    return LocalHashEmbedding()


def is_neural_embedding(provider: EmbeddingProvider) -> bool:
    return not isinstance(provider, LocalHashEmbedding)


def provider_meta(provider: EmbeddingProvider) -> dict[str, Any]:
    return {
        "model_id": provider.model_id,
        "version": provider.version,
        "dimensions": provider.dimensions(),
        "mode": "neural" if is_neural_embedding(provider) else "hash_fallback",
        "runtime": "embedded" if isinstance(provider, LocalNeuralEmbedding) else (
            "openai_compatible" if isinstance(provider, OpenAICompatibleEmbedding) else "hash"
        ),
    }
