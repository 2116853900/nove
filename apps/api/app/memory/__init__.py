"""Long-term memory: embeddings, hybrid retrieval, reindex."""

from .embeddings import EmbeddingProvider, LocalHashEmbedding, OpenAICompatibleEmbedding, resolve_embedding
from .retrieval import HybridRetriever, RetrievalHit

__all__ = [
    "EmbeddingProvider",
    "HybridRetriever",
    "LocalHashEmbedding",
    "OpenAICompatibleEmbedding",
    "RetrievalHit",
    "resolve_embedding",
]
