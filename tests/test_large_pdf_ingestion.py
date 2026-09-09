"""Large-document ingestion verification, without Ollama or application data.

Real PyMuPDF PDFs/parser, production segmentation, temporary SQLite and real
Chroma persistence are exercised. Only rule extraction and embeddings are
deterministic doubles. Strict xfails describe missing authoritative guarantees;
they are not evidence that those acceptance criteria pass.
"""

import textwrap
from types import SimpleNamespace
from unittest.mock import Mock

import pymupdf
import pytest
from fastapi.testclient import TestClient
from langchain_chroma import Chroma
from langchain_core.embeddings import Embeddings
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from ai.rag import create_policy_chunks
from backend.main import app, get_database
from database.db import Base
from database.models import Clause, PolicyFamily, PolicyVersion
from schemas.rule import Rule
from services.pdf_service import extract_pdf_pages


TOPICS = (
    ("Attendance", "Students must maintain 85 percent attendance in each course. "
     "Medical condonation requires a documented decision and is not automatic."),
    ("Library", "Books are issued for fourteen days. A borrower may renew an item "
     "once unless another reader has reserved it. Reference volumes remain onsite."),
    ("Internal assessment", "Internal assessment carries 40 marks: class tests 20, "
     "assignments 10 and laboratory work 10. The minimum required score is 16 marks."),
    ("Laboratory safety", "Students must wear eye protection and closed footwear. "
     "Report spills to the laboratory supervisor immediately; isolate the work area."),
    ("Hostel", "Residents must register overnight visitors with the warden. "
     "Quiet hours begin at 22:00. Emergency exits must remain unobstructed."),
    ("Finance", "A refund request must include the receipt and withdrawal date. "
     "The accounts office records its decision within ten working days."),
    ("Research ethics", "Obtain ethics approval before collecting participant data. "
     "Consent must be voluntary and records must be stored with restricted access."),
    ("IT acceptable use", "Do not share passwords. Report suspected account misuse "
     "to IT services. Access to student records requires a legitimate academic duty."),
)
NAME = "Mixed academic handbook TEST"
VERSION = "2026-test"


def make_mixed_pdf(page_count):
    """Dense, reproducible fixture with tables, numbered clauses and empty pages.

    Returns the independent authored-text oracle along with real PDF bytes.
    No large binary fixture is checked into Git.
    """
    expected = {}
    with pymupdf.open() as document:
        for number in range(1, page_count + 1):
            page = document.new_page(width=595, height=842)
            if number % 17 == 0:
                expected[number] = ""  # deliberately blank separator
                continue
            if number % 23 == 0:
                # A graphics-only campus map has no extractable text.
                page.draw_rect(pymupdf.Rect(70, 90, 400, 400), color=(0, 0, 1))
                expected[number] = ""
                continue
            topic, requirement = TOPICS[(number - 1) % len(TOPICS)]
            paragraphs = [f"PAGE-{number:03d} | {topic} | TEST FIXTURE ONLY"]
            for clause in range(1, 7):
                paragraphs.append(
                    f"P{number:03d}-C{clause:02d}. {requirement} "
                    "The responsible office shall record the application date, "
                    "supporting evidence, decision and reasons. A student may request "
                    "correction of a factual error within three working days. "
                    "This procedure does not replace requirements in other sections."
                )
            paragraphs.extend([
                "Reference table: Office | Record | Review period",
                f"{topic} office | Written decision | 3 working days",
                f"END-PAGE-{number:03d}",
            ])
            authored = "\n\n".join(textwrap.fill(p, width=95) for p in paragraphs)
            remaining = page.insert_textbox(
                pymupdf.Rect(45, 40, 550, 800), authored,
                fontsize=9, fontname="helv", lineheight=1.15,
            )
            assert remaining >= 0, f"Fixture text overflowed page {number}"
            expected[number] = authored
        return document.tobytes(deflate=True), expected


@pytest.fixture(scope="module", params=[50, 75, 100], ids=lambda n: f"{n}-pages")
def large_pdf(request):
    pdf, expected = make_mixed_pdf(request.param)
    return SimpleNamespace(pdf=pdf, expected=expected, count=request.param)


def normalize(text):
    return " ".join(text.split())


def assert_exact_chunk_lineage(documents, metadatas, pages, name=NAME, version=VERSION):
    """Check every character, including late pages and unrelated policy topics."""
    page_text = {p["page_number"]: p["text"] for p in pages}
    coverage = {n: set() for n in page_text}
    assert len(documents) == len(metadatas)
    assert documents
    for content, metadata in zip(documents, metadatas):
        number = metadata["page_number"]
        assert metadata["policy_name"] == name
        assert metadata["version"] == version
        assert isinstance(number, int)
        assert 0 < len(content) <= 800
        assert content in page_text[number], "Chunk crosses pages or alters source text"
        start = page_text[number].index(content)
        coverage[number].update(range(start, start + len(content)))
    assert {m["page_number"] for m in metadatas} == {
        n for n, text in page_text.items() if text
    }
    for number, text in page_text.items():
        assert {i for i, char in enumerate(text) if not char.isspace()} <= coverage[number]


def test_parser_preserves_all_authored_text_and_original_page_numbers(large_pdf):
    pages = extract_pdf_pages(large_pdf.pdf)
    assert len(large_pdf.pdf) < 10 * 1024 * 1024
    assert [p["page_number"] for p in pages] == list(range(1, large_pdf.count + 1))
    for page in pages:
        assert normalize(page["text"]) == normalize(large_pdf.expected[page["page_number"]])
    combined = "\n".join(p["text"] for p in pages)
    assert all(topic in combined for topic, _ in TOPICS)
    assert len(combined) > large_pdf.count * 2000
    assert f"END-PAGE-{large_pdf.count:03d}" in pages[-1]["text"]


def test_segmentation_preserves_every_text_page_without_topic_filtering(large_pdf):
    pages = extract_pdf_pages(large_pdf.pdf)
    chunks = create_policy_chunks(NAME, VERSION, pages)
    assert len(chunks) > large_pdf.count * 3
    assert_exact_chunk_lineage(
        [c.page_content for c in chunks], [c.metadata for c in chunks], pages,
    )


class DeterministicEmbeddings(Embeddings):
    """Persistence tests only: vectors do not test semantic retrieval quality."""

    def embed_documents(self, texts):
        return [[float(len(text) % 101), 1.0, 0.5] for text in texts]

    def embed_query(self, text):
        return self.embed_documents([text])[0]


@pytest.fixture()
def pipeline(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    store = Chroma(
        collection_name="large_pdf_ingestion_test",
        embedding_function=DeterministicEmbeddings(),
        persist_directory=str(tmp_path / "chroma"),
    )
    extract = Mock(return_value=Rule(attendance_requirement=85))
    monkeypatch.setattr("backend.main.extract_attendance_rule", extract)
    monkeypatch.setattr("ai.rag.get_vector_store", lambda: store)

    def database():
        with sessions() as session:
            yield session

    old_overrides = app.dependency_overrides.copy()
    app.dependency_overrides[get_database] = database
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield SimpleNamespace(client=client, sessions=sessions, store=store, extract=extract)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(old_overrides)
        store.delete_collection()
        engine.dispose()


def upload(pipeline, pdf, headers, version=VERSION):
    return pipeline.client.post(
        "/policies/upload", headers=headers,
        data={"policy_name": NAME, "version": version},
        files={"file": ("mixed-handbook.pdf", pdf, "application/pdf")},
    )


def test_authenticated_large_upload_persists_all_chunks_and_rejects_duplicate(
    large_pdf, pipeline, admin_headers,
):
    response = upload(pipeline, large_pdf.pdf, admin_headers)
    assert response.status_code == 200, response.text
    result = response.json()
    pages = extract_pdf_pages(large_pdf.pdf)
    assert result["page_count"] == large_pdf.count
    assert result["status"] == "DRAFT"
    assert pipeline.extract.call_args.args[0] == "\n\n".join(
        f"Page {p['page_number']}:\n{p['text']}" for p in pages if p["text"]
    )
    indexed = pipeline.store.get(include=["documents", "metadatas"])
    assert result["chunk_count"] == len(indexed["ids"])
    assert len(set(indexed["ids"])) == len(indexed["ids"])
    assert_exact_chunk_lineage(indexed["documents"], indexed["metadatas"], pages)
    with pipeline.sessions() as db:
        record = db.get(PolicyVersion, result["id"])
        assert record.family.name == NAME and record.version == VERSION
    duplicate = upload(pipeline, large_pdf.pdf, admin_headers)
    assert duplicate.status_code == 409
    assert set(pipeline.store.get()["ids"]) == set(indexed["ids"])
    assert pipeline.extract.call_count == 1
    assert len(pipeline.client.get("/policies").json()) == 1


def test_large_upload_extraction_failure_leaves_no_data(large_pdf, pipeline, admin_headers):
    pipeline.extract.side_effect = RuntimeError("Simulated model context failure")
    response = upload(pipeline, large_pdf.pdf, admin_headers)
    assert response.status_code == 503
    assert pipeline.store.get()["ids"] == []
    assert pipeline.client.get("/policies").json() == []
    with pipeline.sessions() as db:
        assert db.query(PolicyFamily).count() == 0
        assert db.query(Clause).count() == 0


def test_authoritative_chunk_identifiers_required(pipeline, admin_headers):
    pdf, _ = make_mixed_pdf(100)
    response = upload(pipeline, pdf, admin_headers)
    assert response.status_code == 200, response.text
    version_id = response.json()["id"]
    with pipeline.sessions() as db:
        family_id = db.get(PolicyVersion, version_id).family_id
    indexed = pipeline.store.get(include=["metadatas"])
    assert indexed["metadatas"]
    for metadata in indexed["metadatas"]:
        # PolicyFamily is the logical policy; legacy API id is PolicyVersion.id.
        assert metadata.get("policy_id") == family_id
        assert metadata.get("version_id") == version_id


def test_authoritative_clauses_required_for_all_nonempty_pages(pipeline, admin_headers):
    pdf, _ = make_mixed_pdf(100)
    response = upload(pipeline, pdf, admin_headers)
    assert response.status_code == 200, response.text
    pages = {p["page_number"]: p["text"] for p in extract_pdf_pages(pdf)}
    with pipeline.sessions() as db:
        clauses = db.query(Clause).filter_by(version_id=response.json()["id"]).all()
        assert {c.page_number for c in clauses} == {n for n, text in pages.items() if text}
        for clause in clauses:
            assert clause.source_text == pages[clause.page_number][clause.start_offset:clause.end_offset]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Ingestion gap: failed SQL commit leaves indexed chunks behind")
def test_failed_commit_must_remove_new_chunks(pipeline, admin_headers, monkeypatch):
    pdf, _ = make_mixed_pdf(100)
    def fail_commit(self):
        raise IntegrityError("injected commit failure", {}, RuntimeError("test failure"))
    monkeypatch.setattr(pipeline.sessions.class_, "commit", fail_commit)
    response = upload(pipeline, pdf, admin_headers)
    assert response.status_code == 409
    assert pipeline.client.get("/policies").json() == []
    assert pipeline.store.get()["ids"] == [], "Orphaned source chunks survive a failed upload"
