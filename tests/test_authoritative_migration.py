"""Exercise real Alembic migrations and existing API against migrated SQLite."""
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from backend.main import app, get_database
from core.auth import require_admin
from database.db import Base
from database.models import Clause, PolicyFamily, PolicyVersion, Rule

ROOT = Path(__file__).resolve().parents[1]
LEGACY_ROWS = [
    {'id': 4, 'name': 'Attendance', 'version': '2025', 'attendance_requirement': 75.0, 'status': 'SUPERSEDED'},
    {'id': 9, 'name': 'Attendance', 'version': '2026', 'attendance_requirement': 85.0, 'status': 'CURRENT'},
    {'id': 15, 'name': 'Attendance', 'version': '2027', 'attendance_requirement': 110.0, 'status': 'DRAFT'},
    {'id': 21, 'name': 'Other', 'version': 'draft', 'attendance_requirement': None, 'status': 'DRAFT'},
    {'id': 25, 'name': 'Other', 'version': 'reviewed', 'attendance_requirement': -1.0, 'status': 'VERIFIED'},
]


@pytest.fixture
def migration(tmp_path, monkeypatch):
    url = f'sqlite:///{tmp_path / "migration.db"}'
    monkeypatch.setenv('DATABASE_URL', url)
    config = Config(str(ROOT / 'alembic.ini'))
    config.set_main_option('script_location', str(ROOT / 'alembic'))
    engine = create_engine(url)
    yield config, engine
    engine.dispose()


def seed_legacy(config, engine):
    command.upgrade(config, '0001_initial')
    with engine.begin() as connection:
        connection.execute(text('INSERT INTO policies (id, name, version, attendance_requirement, status) '
                                'VALUES (:id, :name, :version, :attendance_requirement, :status)'), LEGACY_ROWS)


def api_client(engine):
    def database():
        with Session(engine) as session:
            yield session
    app.dependency_overrides[get_database] = database
    app.dependency_overrides[require_admin] = lambda: {'sub': 'migration-test', 'role': 'admin'}
    return TestClient(app)


def test_empty_database_upgrade_and_metadata_match(migration):
    config, engine = migration
    command.upgrade(config, 'head')
    command.upgrade(config, 'head')  # Repeating the migration is harmless.
    assert set(inspect(engine).get_table_names()) == {
        'alembic_version', 'policy_families', 'policy_versions', 'clauses', 'rules',
        'validation_issues', 'rule_reviews', 'index_generations', 'audit_events',
    }
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={'compare_type': True, 'compare_server_default': True})
        assert compare_metadata(context, Base.metadata) == []
        assert connection.execute(text('PRAGMA foreign_key_check')).all() == []


def test_populated_upgrade_preserves_values_ids_statuses_and_marks_no_provenance(migration):
    config, engine = migration
    seed_legacy(config, engine)
    command.upgrade(config, 'head')
    with Session(engine) as session:
        versions = session.query(PolicyVersion).order_by(PolicyVersion.id).all()
        assert [dict(id=v.id, name=v.name, version=v.version,
                     attendance_requirement=v.attendance_requirement, status=v.status)
                for v in versions] == LEGACY_ROWS
        assert session.query(PolicyFamily).count() == 2
        assert session.query(Clause).count() == 0
        assert session.query(Rule).count() == len(LEGACY_ROWS)
        for v in versions:
            assert v.requires_source_reingestion is True
            assert v.supersedes_version_id is None
            assert v.rules[0].legacy_unverified is True
            assert v.rules[0].source_clause_id is None
            assert v.rules[0].attendance_requirement == v.attendance_requirement


def test_legacy_upgrade_downgrade_round_trip_is_lossless(migration):
    config, engine = migration
    seed_legacy(config, engine)
    command.upgrade(config, 'head')
    command.downgrade(config, '0001_initial')
    with engine.connect() as connection:
        assert [dict(row) for row in connection.execute(text('SELECT * FROM policies ORDER BY id')).mappings()] == LEGACY_ROWS
    assert set(inspect(engine).get_table_names()) == {'policies', 'alembic_version'}
    command.upgrade(config, 'head')


@pytest.mark.parametrize('conflict', ['duplicate_current', 'unknown_status'])
def test_conflicting_legacy_lifecycle_rolls_back_without_data_loss(migration, conflict):
    config, engine = migration
    seed_legacy(config, engine)
    with engine.begin() as connection:
        status = 'CURRENT' if conflict == 'duplicate_current' else 'MYSTERY'
        connection.execute(text('UPDATE policies SET status=:status WHERE id=4'), {'status': status})
        before = connection.execute(text('SELECT * FROM policies ORDER BY id')).all()
    with pytest.raises(RuntimeError, match='explicit reconciliation'):
        command.upgrade(config, 'head')
    assert set(inspect(engine).get_table_names()) == {'policies', 'alembic_version'}
    with engine.connect() as connection:
        assert connection.execute(text('SELECT * FROM policies ORDER BY id')).all() == before
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0001_initial'


def test_failure_after_ddl_rolls_back_whole_migration(migration, monkeypatch):
    from sqlalchemy import event
    config, engine = migration
    seed_legacy(config, engine)

    def fail_backfill(connection, cursor, statement, parameters, context, executemany):
        if 'INSERT INTO rules' in statement:
            raise RuntimeError('injected backfill failure')

    event.listen(type(engine), 'before_cursor_execute', fail_backfill)
    try:
        with pytest.raises(RuntimeError, match='injected backfill failure'):
            command.upgrade(config, 'head')
    finally:
        event.remove(type(engine), 'before_cursor_execute', fail_backfill)
    assert set(inspect(engine).get_table_names()) == {'policies', 'alembic_version'}
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM policies')) == len(LEGACY_ROWS)
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0001_initial'


def test_downgrade_refuses_to_discard_new_source_data(migration):
    config, engine = migration
    seed_legacy(config, engine)
    command.upgrade(config, 'head')
    with Session(engine) as session:
        session.add(Clause(version_id=15, page_number=1, start_offset=0,
                           end_offset=3, source_text='85%'))
        session.commit()
    with pytest.raises(RuntimeError, match='discard authoritative data'):
        command.downgrade(config, '0001_initial')
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT count(*) FROM clauses')) == 1
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0003_supporting'


def test_migrated_schema_enforces_same_version_source_and_single_current(migration):
    config, engine = migration
    seed_legacy(config, engine)
    command.upgrade(config, 'head')
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO clauses (id, version_id, page_number, start_offset, end_offset, source_text) VALUES (1,4,1,0,3,'75%')"))
    for statement in (
        'UPDATE policy_versions SET status=\'CURRENT\' WHERE id=4',
        'UPDATE rules SET source_clause_id=1 WHERE version_id=9',
    ):
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(text(statement))


def test_existing_api_creates_families_reuses_names_and_preserves_version_ids(migration):
    config, engine = migration
    seed_legacy(config, engine)
    command.upgrade(config, 'head')
    try:
        with api_client(engine) as client:
            assert client.get('/openapi.json').status_code == 200
            existing = client.get('/policies').json()
            assert {p['id'] for p in existing} == {row['id'] for row in LEGACY_ROWS}
            payload = {'name': 'Attendance', 'version': 'new', 'attendance_requirement': 80}
            created = client.post('/policies', json=payload)
            assert created.status_code == 200
            assert created.json()['id'] > 25
            assert client.post('/policies', json=payload).status_code == 409
            with Session(engine) as session:
                assert session.query(PolicyFamily).filter_by(name='Attendance').count() == 1
    finally:
        app.dependency_overrides.clear()


def test_existing_api_can_supersede_higher_id_current_version(migration):
    config, engine = migration
    seed_legacy(config, engine)
    command.upgrade(config, 'head')
    # Exercise compatibility with valid pre-existing reviewed data. Trust gates
    # are deliberately not implemented in the core-model checkpoint.
    with engine.begin() as connection:
        connection.execute(text("UPDATE policy_versions SET status='VERIFIED' WHERE id=4"))
    try:
        with api_client(engine) as client:
            result = client.post('/policies/4/mark-current')
            assert result.status_code == 200
            assert result.json()['superseded_id'] == 9
            current = [p['id'] for p in client.get('/policies').json() if p['status'] == 'CURRENT']
            assert current == [4]
    finally:
        app.dependency_overrides.clear()


def test_existing_api_can_delete_migrated_source_free_draft(migration):
    from unittest.mock import patch
    config, engine = migration
    seed_legacy(config, engine)
    command.upgrade(config, 'head')
    try:
        with api_client(engine) as client, patch('backend.main.delete_policy_chunks'):
            result = client.delete('/policies/15')
            assert result.status_code == 200
        with Session(engine) as session:
            assert session.get(PolicyVersion, 15) is None
            assert session.query(Rule).filter_by(version_id=15).count() == 0
    finally:
        app.dependency_overrides.clear()
