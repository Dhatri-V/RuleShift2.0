"""Rebuild RuleShift's derived Chroma index from authoritative SQLite clauses."""
from time import monotonic, sleep

import ai.rag as rag
from database.db import SessionLocal
from database.models import PolicyVersion
from services.index_service import rebuild_version_index


REBUILD_BATCH_SIZE = 90
REBUILD_BATCH_INTERVAL_SECONDS = 61


def free_tier_batch_limiter():
    last_batch_started = None

    def before_batch():
        nonlocal last_batch_started
        if last_batch_started is not None:
            remaining = REBUILD_BATCH_INTERVAL_SECONDS - (monotonic() - last_batch_started)
            if remaining > 0:
                sleep(remaining)
        last_batch_started = monotonic()

    return before_batch


def main():
    with SessionLocal() as database:
        versions = (
            database.query(PolicyVersion)
            .filter(PolicyVersion.source_document.has())
            .order_by(PolicyVersion.id)
            .all()
        )
        collection_name = rag.current_collection_name()
        existing_count = len(rag.get_vector_store().get().get("ids", []))
        expected_count = sum(len(version.clauses) for version in versions)
        resume = 0 < existing_count < expected_count
        if resume:
            print(f"resume_collection={collection_name} existing_chunks={existing_count}")
        else:
            rag.reset_current_vector_store()
            print(f"reset_collection={collection_name}")
        before_batch = free_tier_batch_limiter()
        for version in versions:
            try:
                generation = rebuild_version_index(
                    database,
                    version,
                    batch_size=REBUILD_BATCH_SIZE,
                    before_batch=before_batch,
                    preserve_existing=resume,
                )
                database.commit()
                print(f"rebuilt version_id={version.id} generation={generation.generation} chunks={generation.observed_chunk_count}")
            except Exception:
                database.rollback()
                raise
        print(f"rebuilt_versions={len(versions)}")


if __name__ == "__main__":
    main()
