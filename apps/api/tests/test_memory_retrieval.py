from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain import ChapterState
from app.memory.embeddings import LocalHashEmbedding, cosine_similarity
from app.memory.qdrant_store import QdrantVectorStore
from app.memory.retrieval import HybridRetriever, build_query_text, build_query_texts
from app.models import Chapter, ChapterVersion, MemoryChunk
from app.services import ChapterService, ContextAssembler, MemoryService


def test_local_embedding_is_deterministic() -> None:
    provider = LocalHashEmbedding(dimensions=32)
    a = provider.embed_query("信标坠入大气层")
    b = provider.embed_query("信标坠入大气层")
    c = provider.embed_query("完全无关的厨房食谱")
    assert a == b
    assert cosine_similarity(a, b) > 0.99
    assert cosine_similarity(a, c) < cosine_similarity(a, b)


def test_index_writes_embeddings(session: Session) -> None:
    chapter = session.get(Chapter, "c1")
    assert chapter is not None and chapter.current_version_id
    version = session.get(ChapterVersion, chapter.current_version_id)
    assert version is not None

    chunks = MemoryService(session).index_confirmed_version(
        chapter, version, force_reembed=True
    )
    assert chunks
    assert all(not (item.metadata_json or {}).get("embedding") for item in chunks)
    assert all(item.embedding_model_id for item in chunks)
    assert all(item.embedding_dimensions for item in chunks)
    store = QdrantVectorStore(session, chunks[0].embedding_dimensions or 0)
    assert store.missing_chunk_ids(item.id for item in chunks) == set()
    assert chapter.memory_status == "INDEXED"


def test_hybrid_retrieval_prefers_relevant_prior_chapter(session: Session) -> None:
    c1 = session.get(Chapter, "c1")
    c2 = session.get(Chapter, "c2")
    assert c1 and c2 and c1.confirmed_version_id
    v1 = session.get(ChapterVersion, c1.confirmed_version_id)
    assert v1
    MemoryService(session).index_confirmed_version(c1, v1, force_reembed=True)

    # Ensure c2 has a later index and a query about 信标/林远.
    c2.brief = {
        **(c2.brief or {}),
        "goal": "继续追踪信标来源",
        "must_events": ["确认信标坐标"],
        "characters": ["林远"],
    }
    session.commit()

    hits = HybridRetriever(session).search(
        novel_id=c2.novel_id,
        chapter=c2,
        query_text=build_query_text(c2),
        limit=3,
    )
    assert hits
    assert all(hit.chunk.chapter_id == c1.id for hit in hits)
    assert hits[0].score > 0


def test_context_assembler_includes_retrieved_memory(session: Session) -> None:
    c1 = session.get(Chapter, "c1")
    c2 = session.get(Chapter, "c2")
    assert c1 and c2 and c1.confirmed_version_id
    v1 = session.get(ChapterVersion, c1.confirmed_version_id)
    assert v1
    MemoryService(session).index_confirmed_version(c1, v1, force_reembed=True)
    c2.brief = {**(c2.brief or {}), "goal": "信标与林远"}
    session.commit()

    context, sources = ContextAssembler(session).build(c2)
    assert "memory" in context
    assert any(s.get("type") == "memory" for s in sources)
    assert context["outline"]["hierarchy"]
    assert "chapterBrief" not in context["outline"]
    assert any(s.get("type") == "outline" for s in sources)
    assert context["retrievalQueries"] == build_query_texts(c2)
    assert context["budget"]["estimatedTokens"] <= context["budget"]["authoritativeLimit"]


def test_reindex_and_status(session: Session) -> None:
    service = MemoryService(session)
    result = service.reindex_novel("starfarer")
    assert result["confirmedChapters"] >= 1
    assert result["chunks"] >= 1
    status = service.memory_status("starfarer")
    assert status["embeddedChunkCount"] >= 1
    assert status["status"] == "INDEXED"
    assert status["vectorStore"]["backend"] == "qdrant"


def test_reconfirm_marks_later_chapters_outdated(session: Session) -> None:
    c1 = session.get(Chapter, "c1")
    c2 = session.get(Chapter, "c2")
    c3 = session.get(Chapter, "c3")
    assert c1 and c2 and c3
    assert c1.confirmed_version_id
    old_version_id = c1.confirmed_version_id

    # Make later chapters confirmed so impact flags them.
    for chapter in (c2, c3):
        if not chapter.current_version_id:
            ChapterService(session).create_version(
                chapter,
                content=f"{chapter.title} 正文" * 20,
                title=chapter.title,
                source="user",
                base_version_id=None,
            )
        chapter.confirmed_version_id = chapter.current_version_id
        chapter.state = ChapterState.CONFIRMED
        chapter.brief = {
            **(chapter.brief or {}),
            "characters": ["林远"],
            "goal": "与林远有关的后续",
        }
    session.commit()

    new_version = ChapterService(session).create_version(
        c1,
        content=(
            "林远改变了航向，并公开了信标来自泽塔星的新事实。"
            "父亲失踪线索被改写。" * 5
        ),
        title=c1.title,
        source="user",
        base_version_id=c1.current_version_id,
    )
    c1.confirmed_version_id = new_version.id
    c1.state = ChapterState.CONFIRMED
    session.commit()

    result = MemoryService(session).commit_confirmed_memory(
        c1,
        new_version,
        previous_confirmed_version_id=old_version_id,
    )
    assert result["impact"] is not None
    affected_ids = {item["chapterId"] for item in result["impact"]["affectedChapters"]}
    assert c2.id in affected_ids or c3.id in affected_ids

    session.refresh(c2)
    session.refresh(c3)
    assert c2.needs_check or c3.needs_check
    assert c2.state == ChapterState.OUTDATED or c3.state == ChapterState.OUTDATED
