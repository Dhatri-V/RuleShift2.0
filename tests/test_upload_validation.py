"""Focused tests for PDF ingestion robustness and upload validation.

Covers: file-type/size/emptiness validation, corrupted PDFs, image-only
PDFs, duplicate handling, page-number preservation, and safe extraction
failure. Ollama is mocked; SQLite runs in memory.
"""

from unittest.mock import patch

import pymupdf
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.main import app, get_database
from core.auth import require_admin
from database.db import Base


@pytest.fixture()
def client():
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    testing_session = sessionmaker(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    def override_database():
        database = testing_session()
        try:
            yield database
        finally:
            database.close()

    app.dependency_overrides[get_database] = override_database
    # These tests cover upload validation, not authentication.
    app.dependency_overrides[require_admin] = lambda: {"sub": "admin", "role": "admin"}
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        Base.metadata.drop_all(bind=test_engine)
        test_engine.dispose()


def make_pdf(pages_text):
    """Build a real multi-page PDF in memory with pymupdf."""
    document = pymupdf.open()
    for text in pages_text:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


VALID_PDF_TEXT = "Students must maintain a minimum attendance of 85 percent."


# ---------------------------------------------------------------------------
# File type / emptiness / size validation
# ---------------------------------------------------------------------------


def test_non_pdf_extension_rejected(client):
    response = client.post(
        "/policies/upload",
        data={"policy_name": "P", "version": "1"},
        files={"file": ("notes.txt", b"just some text", "text/plain")},
    )

    assert response.status_code == 400
    assert "PDF" in response.json()["detail"]


def test_empty_file_rejected(client):
    response = client.post(
        "/policies/upload",
        data={"policy_name": "P", "version": "1"},
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )

    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_file_without_pdf_signature_rejected(client):
    response = client.post(
        "/policies/upload",
        data={"policy_name": "P", "version": "1"},
        files={"file": ("fake.pdf", b"this is definitely not a pdf", "application/pdf")},
    )

    assert response.status_code == 400
    assert "not a valid PDF" in response.json()["detail"]


def test_corrupted_pdf_rejected(client):
    corrupted = b"%PDF-1.4\nthis looks like a pdf header but the body is garbage"

    response = client.post(
        "/policies/upload",
        data={"policy_name": "P", "version": "1"},
        files={"file": ("broken.pdf", corrupted, "application/pdf")},
    )

    assert response.status_code == 400
    assert "read" in response.json()["detail"].lower() or "pdf" in response.json()["detail"].lower()


def test_oversized_pdf_rejected(client, monkeypatch):
    from core.config import MAX_UPLOAD_BYTES_ENV

    monkeypatch.setenv(MAX_UPLOAD_BYTES_ENV, "1000")  # 1000 bytes
    big_pdf = make_pdf([VALID_PDF_TEXT]) + b" " * 2000

    response = client.post(
        "/policies/upload",
        data={"policy_name": "P", "version": "1"},
        files={"file": ("big.pdf", big_pdf, "application/pdf")},
    )

    assert response.status_code == 413
    assert "too large" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Text extraction validation
# ---------------------------------------------------------------------------


def test_pdf_with_no_extractable_text_rejected(client):
    image_only_pdf = make_pdf(["", ""])  # two blank pages

    response = client.post(
        "/policies/upload",
        data={"policy_name": "P", "version": "1"},
        files={"file": ("scanned.pdf", image_only_pdf, "application/pdf")},
    )

    assert response.status_code == 400
    assert "extractable text" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Valid upload + page metadata
# ---------------------------------------------------------------------------


@patch("backend.main.store_policy_pages")
@patch("backend.main.extract_attendance_rule")
def test_valid_pdf_upload_succeeds(mock_extract, mock_store, client):
    from schemas.rule import Rule

    mock_extract.return_value = Rule(attendance_requirement=85)
    mock_store.return_value = 1
    valid_pdf = make_pdf([VALID_PDF_TEXT])

    response = client.post(
        "/policies/upload",
        data={"policy_name": "Academic Attendance Policy", "version": "2026"},
        files={"file": ("policy.pdf", valid_pdf, "application/pdf")},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "DRAFT"
    assert data["attendance_requirement"] == 85
    assert data["page_count"] == 1
    assert data["chunk_count"] == 1


@patch("backend.main.store_policy_pages")
@patch("backend.main.extract_attendance_rule")
def test_partial_text_pages_keep_correct_page_numbers(mock_extract, mock_store, client):
    """A 3-page PDF where page 2 is blank: page numbers must not shift."""
    from schemas.rule import Rule

    mock_extract.return_value = Rule(attendance_requirement=85)
    mock_store.return_value = 2
    pdf = make_pdf([VALID_PDF_TEXT, "", "Page three has text."])

    response = client.post(
        "/policies/upload",
        data={"policy_name": "Academic Attendance Policy", "version": "2026"},
        files={"file": ("policy.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["page_count"] == 3

    stored_pages = mock_store.call_args[0][2]
    assert [page["page_number"] for page in stored_pages] == [1, 2, 3]
    assert stored_pages[0]["text"].startswith("Students must maintain")
    assert stored_pages[1]["text"] == ""
    assert "Page three" in stored_pages[2]["text"]

    # Chunks are only created for pages with text, keeping real page numbers.
    indexed_pages = mock_store.call_args[0][2]
    assert [p["page_number"] for p in indexed_pages if p["text"]] == [1, 3]


@patch("backend.main.store_policy_pages")
@patch("backend.main.extract_attendance_rule")
def test_page_metadata_survives_into_chunks(mock_extract, mock_store, client):
    from ai.rag import create_policy_chunks
    from schemas.rule import Rule

    mock_extract.return_value = Rule(attendance_requirement=85)
    mock_store.side_effect = lambda name, version, pages: len(
        create_policy_chunks(name, version, pages)
    )
    pdf = make_pdf([VALID_PDF_TEXT, "", "Page three has text."])

    response = client.post(
        "/policies/upload",
        data={"policy_name": "Academic Attendance Policy", "version": "2026"},
        files={"file": ("policy.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 200
    assert response.json()["chunk_count"] >= 2

    chunks = create_policy_chunks(
        "Academic Attendance Policy",
        "2026",
        mock_store.call_args[0][2],
    )
    page_numbers = {chunk.metadata["page_number"] for chunk in chunks}
    assert page_numbers == {1, 3}


# ---------------------------------------------------------------------------
# Duplicate handling
# ---------------------------------------------------------------------------


@patch("backend.main.store_policy_pages")
@patch("backend.main.extract_attendance_rule")
def test_duplicate_policy_version_rejected(mock_extract, mock_store, client):
    from schemas.rule import Rule

    mock_extract.return_value = Rule(attendance_requirement=85)
    mock_store.return_value = 1
    valid_pdf = make_pdf([VALID_PDF_TEXT])

    first = client.post(
        "/policies/upload",
        data={"policy_name": "Academic Attendance Policy", "version": "2026"},
        files={"file": ("policy.pdf", valid_pdf, "application/pdf")},
    )
    assert first.status_code == 200

    duplicate = client.post(
        "/policies/upload",
        data={"policy_name": "Academic Attendance Policy", "version": "2026"},
        files={"file": ("policy.pdf", valid_pdf, "application/pdf")},
    )

    assert duplicate.status_code == 409
    assert "already exists" in duplicate.json()["detail"]
    assert "never overwritten" in duplicate.json()["detail"]

    # The original policy is untouched and only one copy exists.
    policies = client.get("/policies").json()
    matching = [
        p for p in policies
        if p["name"] == "Academic Attendance Policy" and p["version"] == "2026"
    ]
    assert len(matching) == 1


# ---------------------------------------------------------------------------
# Extraction failure handling
# ---------------------------------------------------------------------------


@patch("backend.main.store_policy_pages")
@patch("backend.main.extract_attendance_rule")
def test_extraction_failure_fails_cleanly_without_creating_policy(
    mock_extract, mock_store, client
):
    mock_extract.side_effect = RuntimeError("LLM unavailable")
    valid_pdf = make_pdf([VALID_PDF_TEXT])

    response = client.post(
        "/policies/upload",
        data={"policy_name": "Academic Attendance Policy", "version": "2026"},
        files={"file": ("policy.pdf", valid_pdf, "application/pdf")},
    )

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "Could not extract" in detail
    assert "No policy was created" in detail

    # Nothing was stored and no policy row was created.
    mock_store.assert_not_called()
    assert client.get("/policies").json() == []


@patch("backend.main.store_policy_pages")
@patch("backend.main.extract_attendance_rule")
def test_extraction_failure_does_not_invent_attendance_value(
    mock_extract, mock_store, client
):
    """Even if the LLM returns garbage, a failed upload must not persist."""
    mock_extract.side_effect = ValueError("could not parse structured output")
    valid_pdf = make_pdf([VALID_PDF_TEXT])

    response = client.post(
        "/policies/upload",
        data={"policy_name": "Academic Attendance Policy", "version": "2026"},
        files={"file": ("policy.pdf", valid_pdf, "application/pdf")},
    )

    assert response.status_code == 503
    policies = client.get("/policies").json()
    assert all(p["attendance_requirement"] is not None or p["status"] == "DRAFT"
               for p in policies)
    assert len(policies) == 0