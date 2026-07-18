"""Curated in-process embedding models (fastembed / ONNX)."""

from __future__ import annotations

from typing import Any, TypedDict


class CatalogEntry(TypedDict):
    key: str
    tier: str
    tierLabel: str
    name: str
    modelId: str
    sizeLabel: str
    sizeBytesApprox: int
    dimensions: int
    description: str
    suitableFor: str
    recommended: bool


# Keys are stable API identifiers; modelId must be supported by installed fastembed.
# Verified against fastembed 0.8 TextEmbedding.list_supported_models():
#   - BAAI/bge-small-zh-v1.5          (has HF + GCS)
#   - jinaai/jina-embeddings-v2-base-zh
#   - intfloat/multilingual-e5-large
LOCAL_EMBEDDING_CATALOG: list[CatalogEntry] = [
    {
        "key": "bge-small-zh",
        "tier": "value",
        "tierLabel": "性价比",
        "name": "BGE Small 中文",
        "modelId": "BAAI/bge-small-zh-v1.5",
        "sizeLabel": "~90 MB",
        "sizeBytesApprox": 90 * 1024 * 1024,
        "dimensions": 512,
        "description": "轻量中文语义向量，核显 / 低配 CPU 友好。",
        "suitableFor": "8GB 内存可跑；日常章节检索推荐默认。",
        "recommended": True,
    },
    {
        "key": "jina-base-zh",
        "tier": "mid",
        "tierLabel": "中等",
        "name": "Jina Embeddings v2 中文",
        "modelId": "jinaai/jina-embeddings-v2-base-zh",
        "sizeLabel": "~612 MB",
        "sizeBytesApprox": 641_212_851,  # onnx/model.onnx actual size on mirror
        "dimensions": 768,
        "description": "中文质量更好的中等体量模型（fastembed 内建支持）。",
        "suitableFor": "建议 16GB 内存；需要更稳召回时选用。",
        "recommended": False,
    },
    {
        "key": "e5-large-multi",
        "tier": "high",
        "tierLabel": "较好",
        "name": "Multilingual E5 Large",
        "modelId": "intfloat/multilingual-e5-large",
        "sizeLabel": "~2.2 GB",
        "sizeBytesApprox": int(2.24 * 1024 * 1024 * 1024),
        "dimensions": 1024,
        "description": "多语与长文本更强，体积最大、首载最慢。",
        "suitableFor": "内存 ≥16–24GB 或可接受较慢首载。",
        "recommended": False,
    },
]

_BY_KEY = {item["key"]: item for item in LOCAL_EMBEDDING_CATALOG}
_BY_MODEL_ID = {item["modelId"]: item for item in LOCAL_EMBEDDING_CATALOG}


def get_catalog_entry(key: str) -> CatalogEntry | None:
    return _BY_KEY.get(key)


def get_catalog_entry_by_model_id(model_id: str) -> CatalogEntry | None:
    return _BY_MODEL_ID.get(model_id)


def list_catalog() -> list[CatalogEntry]:
    return list(LOCAL_EMBEDDING_CATALOG)


def catalog_public_row(entry: CatalogEntry, *, downloaded: bool) -> dict[str, Any]:
    return {
        "key": entry["key"],
        "tier": entry["tier"],
        "tierLabel": entry["tierLabel"],
        "name": entry["name"],
        "modelId": entry["modelId"],
        "sizeLabel": entry["sizeLabel"],
        "sizeBytesApprox": entry["sizeBytesApprox"],
        "dimensions": entry["dimensions"],
        "description": entry["description"],
        "suitableFor": entry["suitableFor"],
        "recommended": entry["recommended"],
        "downloaded": downloaded,
    }
