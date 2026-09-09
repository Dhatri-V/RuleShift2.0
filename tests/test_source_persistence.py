"""Source evidence persistence and migration contracts; no live databases."""
from hashlib import sha256
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import IntegrityError

from database.models import Clause, PolicyFamily, PolicyVersion
from database.source_models import SourceDocument, SourcePage
from test_authoritative_migration import migration, seed_legacy  # noqa: F401
from test_large_pdf_ingestion import pipeline, upload, make_mixed_pdf  # noqa: F401


def test_source_roundtrip_chunk_ownership_and_exact_spans(pipeline, admin_headers):
    pdf, _ = make_mixed_pdf(3)
    response = upload(pipeline, pdf, admin_headers)
    assert response.status_code == 200, response.text
    version_id = response.json()['id']
    indexed = pipeline.store.get(include=['metadatas', 'documents'])
    with pipeline.sessions() as db:
        version = db.get(PolicyVersion, version_id)
        source = version.source_document
        assert source.pdf_bytes == pdf
        assert source.sha256 == sha256(pdf).hexdigest()
        assert source.policy_id == version.family_id
        assert source.byte_count == len(pdf) and source.page_count == 3
        assert source.parser.startswith('PyMuPDF ')
        assert not version.requires_source_reingestion
        assert len(version.clauses) == len(indexed['ids'])
        for vector_id, metadata, content in zip(indexed['ids'], indexed['metadatas'], indexed['documents']):
            clause = db.get(Clause, metadata['clause_id'])
            page = db.get(SourcePage, (version_id, metadata['page_number']))
            assert clause.policy_id == metadata['policy_id'] == version.family_id
            assert clause.version_id == metadata['version_id'] == version_id
            assert clause.source_text == content == page.source_text[metadata['start_offset']:metadata['end_offset']]
            assert (clause.start_offset, clause.end_offset) == (metadata['start_offset'], metadata['end_offset'])
            assert metadata['source_sha256'] == source.sha256
            assert vector_id == f'clause:{source.sha256}:{version_id}:{clause.id}'


@pytest.mark.parametrize('statement', [
    "UPDATE source_documents SET sha256 = printf('%064d', 1)",
    "UPDATE source_pages SET source_text = 'tampered'",
    "INSERT OR REPLACE INTO source_documents SELECT * FROM source_documents",
    "INSERT OR REPLACE INTO source_pages SELECT * FROM source_pages",
])
def test_source_identity_and_page_text_cannot_be_rewritten(pipeline, admin_headers, statement):
    pdf, _ = make_mixed_pdf(1)
    assert upload(pipeline, pdf, admin_headers).status_code == 200
    with pipeline.sessions() as db:
        with pytest.raises(IntegrityError, match='immutable'):
            db.execute(text(statement))
        db.rollback()
        assert db.query(SourceDocument).one().pdf_bytes == pdf


def test_same_pdf_new_version_has_distinct_owned_clauses(pipeline, admin_headers):
    pdf, _ = make_mixed_pdf(1)
    first = upload(pipeline, pdf, admin_headers).json()['id']
    second = upload(pipeline, pdf, admin_headers, version='2027-test').json()['id']
    with pipeline.sessions() as db:
        a, b = db.get(PolicyVersion, first), db.get(PolicyVersion, second)
        assert a.source_document.sha256 == b.source_document.sha256
        assert {c.id for c in a.clauses}.isdisjoint({c.id for c in b.clauses})
        assert {c.version_id for c in a.clauses} == {first}
        assert {c.version_id for c in b.clauses} == {second}


def test_index_failure_rolls_back_sql_source_records(pipeline, admin_headers, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError('embedding service unavailable')
    monkeypatch.setattr('backend.main.store_policy_pages', fail)
    pdf, _ = make_mixed_pdf(1)
    assert upload(pipeline, pdf, admin_headers).status_code == 503
    with pipeline.sessions() as db:
        for model in (SourcePage, SourceDocument, Clause, PolicyVersion, PolicyFamily):
            assert db.query(model).count() == 0


def test_uploaded_draft_deletion_removes_owned_sources(pipeline, admin_headers):
    pdf, _ = make_mixed_pdf(1)
    version_id = upload(pipeline, pdf, admin_headers).json()['id']
    response = pipeline.client.delete(f'/policies/{version_id}', headers=admin_headers)
    assert response.status_code == 200, response.text
    assert pipeline.store.get()['ids'] == []
    with pipeline.sessions() as db:
        for model in (SourcePage, SourceDocument, Clause, PolicyVersion):
            assert db.query(model).count() == 0


def test_source_migration_preserves_legacy_and_refuses_lossy_downgrade(migration):
    config, engine = migration
    seed_legacy(config, engine)
    command.upgrade(config, '0003_supporting')
    with engine.connect() as conn:
        before = conn.execute(text('SELECT * FROM policy_versions ORDER BY id')).all()
    command.upgrade(config, 'head')
    with engine.begin() as conn:
        assert conn.execute(text('SELECT * FROM policy_versions ORDER BY id')).all() == before
        assert conn.scalar(text('SELECT count(*) FROM source_documents')) == 0
        owner = conn.execute(text('SELECT family_id, id FROM policy_versions LIMIT 1')).one()
        conn.execute(text('INSERT INTO source_documents (policy_id,version_id,sha256,pdf_bytes,byte_count,page_count,parser) '
                          'VALUES (:policy,:version,:hash,:pdf,4,1,:parser)'),
                     dict(policy=owner.family_id, version=owner.id, hash=sha256(b'test').hexdigest(), pdf=b'test', parser='test'))
    with pytest.raises(RuntimeError, match='discard source evidence'):
        command.downgrade(config, '0003_supporting')
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT version_num FROM alembic_version')) == '0004_source'
        assert conn.scalar(text('SELECT count(*) FROM source_documents')) == 1
    with pytest.raises(IntegrityError, match='immutable'), engine.begin() as conn:
        conn.execute(text("UPDATE source_documents SET parser='tampered'"))


def test_source_migration_failure_rolls_back_schema(migration):
    config, engine = migration
    command.upgrade(config, '0003_supporting')
    def fail(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith('CREATE TRIGGER source_pages_no_replace'):
            raise RuntimeError('injected source migration failure')
    event.listen(type(engine), 'before_cursor_execute', fail)
    try:
        with pytest.raises(RuntimeError, match='injected source migration failure'):
            command.upgrade(config, 'head')
    finally:
        event.remove(type(engine), 'before_cursor_execute', fail)
    assert 'source_documents' not in inspect(engine).get_table_names()
    with engine.connect() as conn:
        assert conn.scalar(text('SELECT version_num FROM alembic_version')) == '0003_supporting'


def test_project_sample_is_real_100_page_pdf_and_uploads(pipeline, admin_headers):
    from services.pdf_service import extract_pdf_pages
    sample = Path(__file__).resolve().parents[1] / 'samples/policies/academic_handbook_100_pages.pdf'
    pdf = sample.read_bytes()
    pages = extract_pdf_pages(pdf)
    assert len(pages) == 100 and all(p['text'] for p in pages)
    for topic in ('Attendance', 'Examinations', 'Internal Assessment', 'Condonation',
                  'Hostel', 'Library', 'Fees', 'Discipline', 'IT and Laboratory', 'Miscellaneous'):
        assert any(topic in p['text'] for p in pages)
    result = upload(pipeline, pdf, admin_headers)
    assert result.status_code == 200, result.text
    assert result.json()['page_count'] == 100
    with pipeline.sessions() as db:
        assert db.query(SourceDocument).one().pdf_bytes == pdf
        assert db.query(SourcePage).count() == 100


def test_source_document_rejects_a_foreign_policy_owner(pipeline):
    with pipeline.sessions() as db:
        first = PolicyFamily(name="Owner A")
        other = PolicyFamily(name="Owner B")
        version = PolicyVersion(family=first, version="1")
        db.add_all([version, other])
        db.flush()
        db.add(SourceDocument(version_id=version.id, policy_id=other.id,
                              sha256=sha256(b"test").hexdigest(), pdf_bytes=b"test",
                              byte_count=4, page_count=1, parser="test"))
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            db.flush()
