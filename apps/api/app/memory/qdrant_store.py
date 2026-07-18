from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Iterable
from uuid import UUID

from qdrant_client import QdrantClient, models
from sqlalchemy.orm import Session

from ..config import settings


@dataclass(frozen=True)
class VectorHit:
    chunk_id: str
    score: float


_clients: dict[str, QdrantClient] = {}
_clients_lock = Lock()


def _point_id(chunk_id: str) -> str:
    try:
        return str(UUID(hex=chunk_id.replace("-", "")))
    except ValueError:
        return str(UUID(bytes=chunk_id.encode("utf-8")[:16].ljust(16, b"\0")))


def _local_path(session: Session) -> str:
    bind = session.get_bind()
    if os.getenv("PYTEST_CURRENT_TEST"):
        return ":memory:"
    database = bind.url.database
    if not database or database == ":memory:":
        return ":memory:"
    return str(Path(database).resolve().parent / "qdrant")


def _client_for(session: Session) -> tuple[QdrantClient, str]:
    if settings.qdrant_url:
        key = f"url:{settings.qdrant_url}"
        factory = lambda: QdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
            timeout=30,
        )
    else:
        location = _local_path(session)
        key = f"local:{location}:{id(session.get_bind()) if location == ':memory:' else ''}"
        factory = (
            (lambda: QdrantClient(location=":memory:"))
            if location == ":memory:"
            else (lambda: QdrantClient(path=location))
        )
    with _clients_lock:
        client = _clients.get(key)
        if client is None:
            client = factory()
            _clients[key] = client
    return client, key


class QdrantVectorStore:
    def __init__(self, session: Session, dimensions: int):
        self.session = session
        self.dimensions = dimensions
        self.client, self.client_key = _client_for(session)
        self.collection = f"{settings.qdrant_collection_prefix}_{dimensions}"
        self._ensure_collection()

    @property
    def mode(self) -> str:
        return "service" if settings.qdrant_url else "local"

    def _ensure_collection(self) -> None:
        if self.client.collection_exists(self.collection):
            return
        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=models.VectorParams(
                size=self.dimensions,
                distance=models.Distance.COSINE,
            ),
        )
        if settings.qdrant_url:
            for field in (
                "workspace_id",
                "novel_id",
                "chapter_id",
                "version_id",
                "model_id",
                "model_version",
            ):
                self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )
            self.client.create_payload_index(
                collection_name=self.collection,
                field_name="chapter_index",
                field_schema=models.PayloadSchemaType.INTEGER,
            )

    def upsert(
        self,
        chunks: Iterable[Any],
        vectors: list[list[float]],
        *,
        model_id: str,
        model_version: str,
    ) -> None:
        chunk_list = list(chunks)
        if len(chunk_list) != len(vectors):
            raise ValueError("chunk/vector count mismatch")
        points = []
        for chunk, vector in zip(chunk_list, vectors):
            meta = chunk.metadata_json or {}
            points.append(
                models.PointStruct(
                    id=_point_id(chunk.id),
                    vector=vector,
                    payload={
                        "chunk_id": chunk.id,
                        "workspace_id": chunk.workspace_id,
                        "novel_id": chunk.novel_id,
                        "chapter_id": chunk.chapter_id,
                        "version_id": chunk.version_id,
                        "chapter_index": int(meta.get("chapterIndex") or 0),
                        "model_id": model_id,
                        "model_version": model_version,
                    },
                )
            )
        if points:
            self.client.upsert(
                collection_name=self.collection,
                points=points,
                wait=True,
            )

    def missing_chunk_ids(self, chunk_ids: Iterable[str]) -> set[str]:
        ids = list(dict.fromkeys(chunk_ids))
        if not ids:
            return set()
        records = self.client.retrieve(
            collection_name=self.collection,
            ids=[_point_id(chunk_id) for chunk_id in ids],
            with_payload=True,
            with_vectors=False,
        )
        found = {
            str(record.payload.get("chunk_id"))
            for record in records
            if record.payload and record.payload.get("chunk_id")
        }
        return set(ids) - found

    def delete(self, chunk_ids: Iterable[str]) -> None:
        ids = list(dict.fromkeys(chunk_ids))
        if not ids:
            return
        self.client.delete(
            collection_name=self.collection,
            points_selector=models.PointIdsList(
                points=[_point_id(chunk_id) for chunk_id in ids]
            ),
            wait=True,
        )

    def search(
        self,
        query_vector: list[float],
        *,
        workspace_id: str,
        novel_id: str,
        prior_chapter_ids: Iterable[str],
        model_id: str,
        model_version: str,
        limit: int,
    ) -> list[VectorHit]:
        chapter_ids = list(prior_chapter_ids)
        if not chapter_ids:
            return []
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="workspace_id", match=models.MatchValue(value=workspace_id)
                ),
                models.FieldCondition(
                    key="novel_id", match=models.MatchValue(value=novel_id)
                ),
                models.FieldCondition(
                    key="chapter_id", match=models.MatchAny(any=chapter_ids)
                ),
                models.FieldCondition(
                    key="model_id", match=models.MatchValue(value=model_id)
                ),
                models.FieldCondition(
                    key="model_version",
                    match=models.MatchValue(value=model_version),
                ),
            ]
        )
        response = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return [
            VectorHit(
                chunk_id=str(point.payload.get("chunk_id")),
                score=float(point.score),
            )
            for point in response.points
            if point.payload and point.payload.get("chunk_id")
        ]

    def count(
        self,
        *,
        workspace_id: str,
        novel_id: str,
        model_id: str,
        model_version: str,
    ) -> int:
        result = self.client.count(
            collection_name=self.collection,
            count_filter=models.Filter(
                must=[
                    models.FieldCondition(
                        key="workspace_id",
                        match=models.MatchValue(value=workspace_id),
                    ),
                    models.FieldCondition(
                        key="novel_id", match=models.MatchValue(value=novel_id)
                    ),
                    models.FieldCondition(
                        key="model_id", match=models.MatchValue(value=model_id)
                    ),
                    models.FieldCondition(
                        key="model_version",
                        match=models.MatchValue(value=model_version),
                    ),
                ]
            ),
            exact=True,
        )
        return int(result.count)

    def status(self) -> dict[str, Any]:
        return {
            "backend": "qdrant",
            "mode": self.mode,
            "collection": self.collection,
            "dimensions": self.dimensions,
            "url": settings.qdrant_url or None,
        }


def delete_chunk_vectors(session: Session, chunks: Iterable[Any]) -> None:
    grouped: dict[int, list[str]] = {}
    for chunk in chunks:
        dimensions = chunk.embedding_dimensions
        if not dimensions:
            legacy = (chunk.metadata_json or {}).get("embedding")
            dimensions = len(legacy) if isinstance(legacy, list) else 0
        if dimensions:
            grouped.setdefault(int(dimensions), []).append(chunk.id)
    for dimensions, chunk_ids in grouped.items():
        QdrantVectorStore(session, dimensions).delete(chunk_ids)


def qdrant_status(session: Session) -> dict[str, Any]:
    try:
        client, _ = _client_for(session)
        collections = [item.name for item in client.get_collections().collections]
        return {
            "backend": "qdrant",
            "available": True,
            "mode": "service" if settings.qdrant_url else "local",
            "url": settings.qdrant_url or None,
            "collections": collections,
        }
    except Exception as exc:
        return {
            "backend": "qdrant",
            "available": False,
            "mode": "service" if settings.qdrant_url else "local",
            "url": settings.qdrant_url or None,
            "error": str(exc),
        }
