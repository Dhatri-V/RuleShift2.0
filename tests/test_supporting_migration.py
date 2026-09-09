"""Real migration/SQLite checks for supporting records; no live DB or Chroma."""
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.db import Base
from database.models import AuditEvent
from test_authoritative_migration import migration, seed_legacy  # noqa: F401
from test_supporting_models import audit, generation, issue, make_graph, review

SUPPORTING_TABLES = {'validation_issues', 'rule_reviews', 'index_generations', 'audit_events'}
CORE_TABLES = ('policy_families', 'policy_versions', 'clauses', 'rules')


def snapshot(connection):
    return {table: connection.execute(text(f'SELECT * FROM {table} ORDER BY id')).all()
            for table in CORE_TABLES}


def seed_core(config, engine):
    seed_legacy(config, engine)
    command.upgrade(config, '0002_core')
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO clauses (id,version_id,page_number,start_offset,end_offset,source_text) "
                                "VALUES (101,15,3,0,4,'110%')"))
        connection.execute(text('INSERT INTO rules (id,version_id,source_clause_id,attendance_requirement,legacy_unverified) '
                                'VALUES (1001,15,101,110,0)'))
        return snapshot(connection)


def test_empty_upgrade_schema_defaults_indexes_and_metadata_match(migration):
    config, engine = migration
    command.upgrade(config, 'head')
    command.upgrade(config, 'head')
    assert set(inspect(engine).get_table_names()) == set(CORE_TABLES) | SUPPORTING_TABLES | {'alembic_version', 'source_documents', 'source_pages'}
    with engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={'compare_type': True, 'compare_server_default': True})
        assert compare_metadata(context, Base.metadata) == []
        assert connection.execute(text('PRAGMA foreign_key_check')).all() == []
        triggers = set(connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'")).scalars())
        assert triggers == {'audit_events_no_update', 'audit_events_no_delete', 'audit_events_no_replace',
                            'source_documents_no_update', 'source_documents_no_replace',
                            'source_pages_no_update', 'source_pages_no_replace'}
        for table in SUPPORTING_TABLES:
            assert connection.scalar(text(f'SELECT count(*) FROM {table}')) == 0


def test_populated_core_upgrade_preserves_all_data_and_infers_no_supporting_results(migration):
    config, engine = migration
    before = seed_core(config, engine)
    command.upgrade(config, 'head')
    with engine.connect() as connection:
        assert snapshot(connection) == before
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0004_source'
        for table in SUPPORTING_TABLES:
            assert connection.scalar(text(f'SELECT count(*) FROM {table}')) == 0
        assert connection.execute(text('PRAGMA foreign_key_check')).all() == []


def test_empty_supporting_downgrade_preserves_populated_core_and_reupgrade(migration):
    config, engine = migration
    before = seed_core(config, engine)
    command.upgrade(config, 'head')
    command.downgrade(config, '0002_core')
    with engine.connect() as connection:
        assert snapshot(connection) == before
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0002_core'
        assert connection.scalar(text("SELECT count(*) FROM sqlite_master WHERE type='trigger'")) == 0
    assert set(inspect(engine).get_table_names()) == set(CORE_TABLES) | {'alembic_version'}
    assert 'uq_rule_version_id' not in {i['name'] for i in inspect(engine).get_indexes('rules')}
    command.upgrade(config, 'head')
    with engine.connect() as connection:
        assert snapshot(connection) == before


@pytest.mark.parametrize('kind', ['issue', 'review', 'index', 'audit'])
def test_downgrade_refuses_each_kind_of_supporting_data(migration, kind):
    config, engine = migration
    command.upgrade(config, 'head')
    with Session(engine) as session:
        graph = make_graph(session)
        session.add({'issue': issue, 'review': review, 'index': generation, 'audit': audit}[kind](graph))
        session.commit()
    with pytest.raises(RuntimeError, match='discard supporting records'):
        command.downgrade(config, '0002_core')
    with engine.connect() as connection:
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0004_source'
        table = {'issue': 'validation_issues', 'review': 'rule_reviews', 'index': 'index_generations', 'audit': 'audit_events'}[kind]
        assert connection.scalar(text(f'SELECT count(*) FROM {table}')) == 1


def test_failed_upgrade_rolls_back_created_tables_index_and_revision(migration):
    config, engine = migration
    before = seed_core(config, engine)

    def fail_late(connection, cursor, statement, parameters, context, executemany):
        if statement.startswith('CREATE TRIGGER audit_events_no_delete'):
            raise RuntimeError('injected migration failure')

    event.listen(type(engine), 'before_cursor_execute', fail_late)
    try:
        with pytest.raises(RuntimeError, match='injected migration failure'):
            command.upgrade(config, 'head')
    finally:
        event.remove(type(engine), 'before_cursor_execute', fail_late)
    with engine.connect() as connection:
        assert snapshot(connection) == before
        assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0002_core'
        assert connection.scalar(text("SELECT count(*) FROM sqlite_master WHERE type='trigger'")) == 0
    assert set(inspect(engine).get_table_names()) == set(CORE_TABLES) | {'alembic_version'}
    assert 'uq_rule_version_id' not in {i['name'] for i in inspect(engine).get_indexes('rules')}
    command.upgrade(config, 'head')


def test_migrated_records_round_trip_and_database_defaults(migration):
    config, engine = migration
    command.upgrade(config, 'head')
    with Session(engine) as session:
        graph = make_graph(session)
        session.add_all([issue(graph), review(graph), generation(graph), audit(graph)])
        session.commit()
        session.expire_all()
        assert graph.r1.review.status == 'PENDING_REVIEW'
        assert graph.v1.validation_issues[0].status == 'OPEN'
        assert graph.v1.index_generations[0].status == 'PENDING'
        assert graph.v1.audit_events[0].after_state == {'status': 'APPROVED'}
    with engine.connect() as connection:
        assert connection.execute(text('PRAGMA foreign_key_check')).all() == []


@pytest.mark.parametrize('operation', ['update', 'delete', 'replace'])
def test_migrated_audit_triggers_protect_history(migration, operation):
    config, engine = migration
    command.upgrade(config, 'head')
    with Session(engine) as session:
        graph = make_graph(session)
        record = audit(graph)
        session.add(record)
        session.commit()
        record_id, family_id = record.id, graph.family.id
    statements = {
        'update': "UPDATE audit_events SET action='TAMPER' WHERE id=:id",
        'delete': 'DELETE FROM audit_events WHERE id=:id',
        'replace': "INSERT OR REPLACE INTO audit_events (id,family_id,actor_type,actor_id,action) VALUES (:id,:family,'SYSTEM','tamper','REPLACE')",
    }
    with pytest.raises(IntegrityError, match='append-only'), engine.begin() as connection:
        connection.execute(text(statements[operation]), {'id': record_id, 'family': family_id})
    with Session(engine) as session:
        assert session.get(AuditEvent, record_id).action == 'RULE_REVIEW_RECORDED'


@pytest.mark.parametrize('target', ['issue_rule', 'issue_clause', 'audit_family', 'audit_rule', 'audit_clause'])
def test_migrated_schema_rejects_cross_version_references(migration, target):
    config, engine = migration
    command.upgrade(config, 'head')
    with Session(engine) as session:
        graph = make_graph(session)
        record = {
            'issue_rule': lambda: issue(graph, rule_id=graph.r2.id),
            'issue_clause': lambda: issue(graph, clause_id=graph.c2.id),
            'audit_family': lambda: audit(graph, family_id=graph.other_family.id),
            'audit_rule': lambda: audit(graph, rule_id=graph.r2.id),
            'audit_clause': lambda: audit(graph, clause_id=graph.c2.id),
        }[target]()
        session.add(record)
        with pytest.raises(IntegrityError):
            session.commit()


def test_migrated_audit_insert_rolls_back_with_core_mutation(migration):
    config, engine = migration
    command.upgrade(config, 'head')
    with Session(engine) as session:
        graph = make_graph(session)
        graph.v1.attendance_requirement = 99
        session.add(audit(graph))
        session.flush()
        session.rollback()
        assert graph.v1.attendance_requirement == 75
        assert session.query(AuditEvent).count() == 0
