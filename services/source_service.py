"""Persist source evidence and prepare the existing page chunks for indexing."""
from hashlib import sha256

import pymupdf

from ai.rag import create_policy_chunks
from database.models import Clause
from database.source_models import SourceDocument, SourcePage


def persist_source(database, version, pdf_bytes, pages):
    """Caller owns commit/rollback; no vector or filesystem writes happen here.

    Offsets are half-open Unicode character spans in the exact persisted parser
    output, not PDF byte offsets or visual coordinates. A Clause is an
    authoritative text segment, not an extracted or approved executable rule.
    """
    digest = sha256(pdf_bytes).hexdigest()
    source = SourceDocument(
        version=version, policy_id=version.family_id, sha256=digest,
        pdf_bytes=pdf_bytes, byte_count=len(pdf_bytes), page_count=len(pages),
        parser=f"PyMuPDF {pymupdf.VersionBind}; text; sort=True; strip=True",
    )
    database.add(source)
    database.flush()
    for page in pages:
        database.add(SourcePage(version_id=version.id, **{
            "page_number": page["page_number"], "source_text": page["text"],
        }))
    chunks = create_policy_chunks(version.name, version.version, pages)
    page_text = {p["page_number"]: p["text"] for p in pages}
    pairs = []
    for chunk in chunks:
        start = chunk.metadata["start_index"]
        end = start + len(chunk.page_content)
        number = chunk.metadata["page_number"]
        if start < 0 or page_text[number][start:end] != chunk.page_content:
            raise ValueError("Chunk does not match its source page span")
        clause = Clause(version=version, page_number=number, start_offset=start,
                        end_offset=end, source_text=chunk.page_content)
        database.add(clause)
        pairs.append((clause, chunk))
    database.flush()
    for clause, chunk in pairs:
        chunk.metadata.update(
            policy_id=version.family_id, version_id=version.id, clause_id=clause.id,
            source_sha256=digest, start_offset=clause.start_offset, end_offset=clause.end_offset,
        )
    version.requires_source_reingestion = False
    return chunks
