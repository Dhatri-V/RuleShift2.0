"""Derived-index lifecycle and consistency checks.

SQLite records which generation is READY. Chroma remains disposable: uploads
compensate failed SQL transactions and this module can rebuild a version from
its authoritative clauses.
"""
from hashlib import sha256
import json
from datetime import datetime

from fastapi import HTTPException

import ai.rag as rag
from ai.rag import policy_chunk_ids, store_policy_pages
from database.supporting_models import IndexGeneration
from core.config import get_embedding_identity


def _manifest(chunks):
    rows = [
        {
            "id": chunk_id,
            "page": chunk.metadata.get("page_number"),
            "start": chunk.metadata.get("start_offset"),
            "end": chunk.metadata.get("end_offset"),
        }
        for chunk_id, chunk in zip(policy_chunk_ids(chunks), chunks)
    ]
    return sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def begin_generation(database, version, chunks):
    generation_number = 1 + max((row.generation for row in version.index_generations), default=0)
    row = IndexGeneration(
        version=version,
        generation=generation_number,
        status="BUILDING",
        collection_name=rag.current_collection_name(),
        embedding_model=get_embedding_identity(),
        chunking_config={"chunk_size": 800, "chunk_overlap": 100, "page_scoped": True},
        expected_chunk_count=len(chunks),
        manifest_sha256=_manifest(chunks),
    )
    database.add(row)
    database.flush()
    for chunk in chunks:
        chunk.metadata["index_generation"] = generation_number
    return row


def mark_generation_ready(row, observed_count):
    row.observed_chunk_count = observed_count
    row.status = "READY" if observed_count == row.expected_chunk_count else "FAILED"
    row.completed_at = datetime.utcnow()
    if row.status == "FAILED":
        row.failure_detail = (
            f"Expected {row.expected_chunk_count} chunks but indexed {observed_count}."
        )


def observed_version_chunks(version_id):
    result = rag.get_vector_store().get(where={"version_id": {"$eq": version_id}})
    return len(result.get("ids", []))


def require_healthy_index(version):
    ready = [row for row in version.index_generations if row.status == "READY"]
    if not ready:
        raise HTTPException(status_code=409, detail="Publication blocked: no READY index generation exists.")
    embedding_identity = get_embedding_identity()
    collection_name = rag.current_collection_name()
    compatible = [
        row for row in ready
        if row.embedding_model == embedding_identity
        and row.collection_name == collection_name
    ]
    if not compatible:
        raise HTTPException(
            status_code=409,
            detail=(
                "Publication blocked: READY index generation is stale or incompatible "
                f"with embedding model {embedding_identity}. Rebuild the vector index."
            ),
        )
    generation = max(compatible, key=lambda row: row.generation)
    expected = len(version.clauses)
    observed = observed_version_chunks(version.id)
    if (
        generation.expected_chunk_count != expected
        or generation.observed_chunk_count != expected
        or observed != expected
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Publication blocked: vector index mismatch "
                f"(clauses={expected}, recorded={generation.observed_chunk_count}, observed={observed})."
            ),
        )
    return generation


def rebuild_version_index(
    database,
    version,
    *,
    batch_size=None,
    before_batch=None,
    preserve_existing=False,
):
    """Rebuild one derived version index from immutable SQLite clauses."""
    from langchain_core.documents import Document
    from ai.rag import delete_policy_chunks

    source = version.source_document
    if source is None:
        raise ValueError("Cannot rebuild an index without an authoritative source document")
    chunks = [
        Document(
            page_content=clause.source_text,
            metadata={
                "policy_name": version.name,
                "version": version.version,
                "page_number": clause.page_number,
                "policy_id": version.family_id,
                "version_id": version.id,
                "clause_id": clause.id,
                "source_sha256": source.sha256,
                "start_offset": clause.start_offset,
                "end_offset": clause.end_offset,
            },
        )
        for clause in sorted(version.clauses, key=lambda item: (item.page_number, item.start_offset))
    ]
    if preserve_existing:
        existing_ids = set(
            rag.get_vector_store().get(where={"version_id": {"$eq": version.id}}).get("ids", [])
        )
        chunk_pairs = [
            (chunk_id, chunk)
            for chunk_id, chunk in zip(policy_chunk_ids(chunks), chunks)
            if chunk_id not in existing_ids
        ]
        chunks_to_store = [chunk for _, chunk in chunk_pairs]
    else:
        delete_policy_chunks(version.name, version.version)
        chunks_to_store = chunks
    row = begin_generation(database, version, chunks)
    batches = (
        [chunks_to_store]
        if batch_size is None
        else [
            chunks_to_store[start:start + batch_size]
            for start in range(0, len(chunks_to_store), batch_size)
        ]
    )
    for batch in batches:
        if not batch:
            continue
        if before_batch is not None:
            before_batch()
        store_policy_pages(version.name, version.version, [], chunks=batch)
    observed = observed_version_chunks(version.id)
    mark_generation_ready(row, observed)
    if row.status != "READY":
        raise RuntimeError(row.failure_detail)
    return row
