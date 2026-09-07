"""Checkpoint 1B persistence contracts, with no workflow/model service calls."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.db import Base
from database.models import (
    AuditEvent, Clause, IndexGeneration, PolicyFamily, PolicyVersion, Rule,
    RuleReview, ValidationIssue,
)

STAMP = datetime(2026, 9, 7, 12)
LATER = STAMP + timedelta(seconds=1)


@pytest.fixture
def session():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def make_graph(session):
    family = PolicyFamily(name='Attendance')
    other_family = PolicyFamily(name='Other')
    versions = [PolicyVersion(family=family, version='v1', attendance_requirement=75),
                PolicyVersion(family=family, version='v2', attendance_requirement=85),
                PolicyVersion(family=other_family, version='v1', attendance_requirement=85)]
    session.add_all(versions)
    session.flush()
    clauses = [Clause(version=v, page_number=1, start_offset=0, end_offset=3, source_text='85%')
               for v in versions]
    session.add_all(clauses)
    session.flush()
    rules = [Rule(version=v, source_clause=c, attendance_requirement=85)
             for v, c in zip(versions, clauses)]
    session.add_all(rules)
    session.commit()
    return SimpleNamespace(family=family, other_family=other_family,
                           v1=versions[0], v2=versions[1], foreign=versions[2],
                           c1=clauses[0], c2=clauses[1], r1=rules[0], r2=rules[1])


@pytest.fixture
def graph(session):
    return make_graph(session)


def issue(g, **changes):
    values = dict(version_id=g.v1.id, rule_id=g.r1.id, clause_id=g.c1.id,
                  code='LITERAL_MISMATCH', message='Source differs from candidate.',
                  validator='literal-v1', created_at=STAMP)
    values.update(changes)
    return ValidationIssue(**values)


def review(g, **changes):
    values = dict(rule_id=g.r1.id, created_at=STAMP)
    values.update(changes)
    return RuleReview(**values)


def generation(g, **changes):
    values = dict(version_id=g.v1.id, generation=1, collection_name='policies-v1-g1',
                  embedding_model='nomic-embed-text', chunking_config={'size': 800, 'overlap': 100},
                  created_at=STAMP)
    values.update(changes)
    return IndexGeneration(**values)


def audit(g, **changes):
    values = dict(family_id=g.family.id, version_id=g.v1.id, rule_id=g.r1.id,
                  clause_id=g.c1.id, actor_type='ADMIN', actor_id='synthetic-reviewer',
                  action='RULE_REVIEW_RECORDED', before_state={'status': 'PENDING_REVIEW'},
                  after_state={'status': 'APPROVED'}, reason='Source checked.', correlation_id='test-request')
    values.update(changes)
    return AuditEvent(**values)


def test_all_supporting_records_round_trip_and_relationships(session, graph):
    records = [issue(graph), review(graph), generation(graph), audit(graph)]
    session.add_all(records)
    session.commit()
    session.expire_all()
    finding, decision, index, event = records
    assert finding.status == 'OPEN' and finding.is_blocking is True
    assert finding.rule is graph.r1 and finding.clause is graph.c1
    assert graph.v1.validation_issues == [finding]
    assert graph.r1.validation_issues == [finding]
    assert graph.r1.review is decision and decision.rule is graph.r1
    assert decision.status == 'PENDING_REVIEW' and decision.reviewer_id is None
    assert index.status == 'PENDING' and index.observed_chunk_count is None
    assert index.chunking_config == {'size': 800, 'overlap': 100}
    assert graph.v1.index_generations == [index]
    assert event.after_state == {'status': 'APPROVED'}
    assert event.before_state == {'status': 'PENDING_REVIEW'}
    assert event.occurred_at is not None
    assert graph.family.audit_events == [event] and graph.v1.audit_events == [event]
    assert event.version is graph.v1 and event.rule is graph.r1 and event.clause is graph.c1


def test_version_only_issue_and_family_only_audit_are_supported(session, graph):
    finding = issue(graph, rule_id=None, clause_id=None)
    event = audit(graph, version_id=None, rule_id=None, clause_id=None, action='FAMILY_CREATED')
    session.add_all([finding, event])
    session.commit()
    assert finding.rule is None and finding.clause is None
    assert event.version is None and event.family is graph.family


@pytest.mark.parametrize('changes', [
    {'code': ''}, {'message': ' '}, {'validator': ''}, {'severity': 'FATAL'},
    {'severity': 'WARNING', 'is_blocking': True}, {'status': 'IGNORED'},
    {'status': 'RESOLVED'}, {'resolved_by': 'admin'},
    {'status': 'RESOLVED', 'resolved_by': 'admin', 'resolved_at': LATER},
    {'status': 'RESOLVED', 'resolved_by': ' ', 'resolved_at': LATER, 'resolution_note': 'fixed'},
    {'status': 'RESOLVED', 'resolved_by': 'admin', 'resolved_at': STAMP-timedelta(seconds=1), 'resolution_note': 'fixed'},
])
def test_invalid_validation_metadata_rejected(session, graph, changes):
    session.add(issue(graph, **changes))
    with pytest.raises(IntegrityError):
        session.commit()


def test_resolved_issue_retains_original_details(session, graph):
    finding = issue(graph)
    session.add(finding)
    session.commit()
    finding.status = 'RESOLVED'
    finding.resolved_by = 'synthetic-reviewer'
    finding.resolved_at = LATER
    finding.resolution_note = 'Corrected extracted literal.'
    session.commit()
    session.expire_all()
    assert finding.code == 'LITERAL_MISMATCH' and finding.created_at == STAMP
    assert finding.resolution_note == 'Corrected extracted literal.'


@pytest.mark.parametrize('status', ['APPROVED', 'REJECTED', 'NON_EXECUTABLE'])
def test_review_decision_metadata_round_trip_without_changing_rule(session, graph, status):
    decision = review(graph, status=status, reviewer_id='reviewer', reviewed_at=LATER,
                      reason='Document inspected.', rule_snapshot={'attendance_requirement': 85})
    session.add(decision)
    session.commit()
    session.expire_all()
    assert decision.status == status and decision.rule_snapshot == {'attendance_requirement': 85}
    assert graph.r1.attendance_requirement == 85
    assert graph.v1.status == 'DRAFT' and graph.v1.requires_source_reingestion is True


@pytest.mark.parametrize('changes', [
    {'status': 'INVALID'}, {'status': 'APPROVED'}, {'status': 'REJECTED'},
    {'status': 'NON_EXECUTABLE'}, {'reviewer_id': 'reviewer'}, {'reviewed_at': LATER},
    {'status': 'APPROVED', 'reviewer_id': '', 'reviewed_at': LATER, 'reason': 'checked', 'rule_snapshot': {}},
    {'status': 'APPROVED', 'reviewer_id': 'reviewer', 'reviewed_at': LATER, 'reason': 'checked'},
    {'status': 'APPROVED', 'reviewer_id': 'reviewer', 'reviewed_at': STAMP-timedelta(seconds=1), 'reason': 'checked', 'rule_snapshot': {}},
])
def test_invalid_review_metadata_rejected(session, graph, changes):
    session.add(review(graph, **changes))
    with pytest.raises(IntegrityError):
        session.commit()


def test_review_is_unique_per_rule(session, graph):
    session.add_all([review(graph), review(graph)])
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize('changes', [
    {'generation': 0}, {'generation': 1.5}, {'status': 'ACTIVE'},
    {'expected_chunk_count': -1}, {'expected_chunk_count': 1.5},
    {'observed_chunk_count': -1}, {'observed_chunk_count': 0.5},
    {'collection_name': ''}, {'embedding_model': ' '}, {'chunking_config': None},
    {'manifest_sha256': 'not-a-hash'}, {'manifest_sha256': 'g'*64},
    {'completed_at': STAMP-timedelta(seconds=1)},
])
def test_invalid_index_metadata_rejected(session, graph, changes):
    session.add(generation(graph, **changes))
    with pytest.raises(IntegrityError):
        session.commit()


def test_generation_number_unique_within_version(session, graph):
    session.add_all([generation(graph), generation(graph)])
    with pytest.raises(IntegrityError):
        session.commit()


def test_generation_numbers_scoped_to_versions_and_failed_counts_preserved(session, graph):
    session.add_all([
        generation(graph, status='FAILED', expected_chunk_count=2, observed_chunk_count=3,
                   manifest_sha256='a'*64, failure_detail='Extra chunk detected.', completed_at=LATER),
        generation(graph, generation=2),
        generation(graph, version_id=graph.v2.id),
    ])
    session.commit()
    assert session.query(IndexGeneration).count() == 3
    failed = session.query(IndexGeneration).filter_by(status='FAILED').one()
    assert failed.observed_chunk_count == 3 and failed.failure_detail == 'Extra chunk detected.'
    assert graph.v1.status == 'DRAFT'


@pytest.mark.parametrize('target', ['issue_rule', 'issue_clause', 'audit_rule', 'audit_clause', 'audit_family'])
def test_cross_version_and_family_references_rejected(session, graph, target):
    records = {
        'issue_rule': lambda: issue(graph, rule_id=graph.r2.id),
        'issue_clause': lambda: issue(graph, clause_id=graph.c2.id),
        'audit_rule': lambda: audit(graph, rule_id=graph.r2.id),
        'audit_clause': lambda: audit(graph, clause_id=graph.c2.id),
        'audit_family': lambda: audit(graph, family_id=graph.other_family.id),
    }
    session.add(records[target]())
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize('kind', ['issue', 'review', 'index', 'audit'])
def test_missing_parents_rejected(session, graph, kind):
    record = {'issue': lambda: issue(graph, version_id=999),
              'review': lambda: review(graph, rule_id=999),
              'index': lambda: generation(graph, version_id=999),
              'audit': lambda: audit(graph, family_id=999)}[kind]()
    session.add(record)
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize('changes', [
    {'actor_id': ''}, {'action': ''}, {'actor_type': 'STUDENT'}, {'version_id': None}, {'id': -1},
])
def test_invalid_audit_metadata_rejected(session, graph, changes):
    session.add(audit(graph, **changes))
    with pytest.raises(IntegrityError):
        session.commit()


@pytest.mark.parametrize('operation', ['orm_update', 'orm_delete', 'sql_update', 'sql_delete', 'sql_replace'])
def test_audit_events_are_append_only(session, graph, operation):
    event = audit(graph)
    session.add(event)
    session.commit()
    event_id = event.id
    with pytest.raises(IntegrityError, match='append-only'):
        if operation == 'orm_update':
            event.reason = 'tampered'
        elif operation == 'orm_delete':
            session.delete(event)
        elif operation == 'sql_update':
            session.execute(text("UPDATE audit_events SET reason='tampered' WHERE id=:id"), {'id': event_id})
        elif operation == 'sql_delete':
            session.execute(text('DELETE FROM audit_events WHERE id=:id'), {'id': event_id})
        else:
            session.execute(text('INSERT OR REPLACE INTO audit_events (id,family_id,actor_type,actor_id,action) '
                                 "VALUES (:id,:family,'SYSTEM','tamper','REPLACED')"), {'id': event_id, 'family': graph.family.id})
        session.commit()
    session.rollback()
    assert session.get(AuditEvent, event_id).reason == 'Source checked.'


def test_audit_and_model_changes_share_transaction_rollback(session, graph):
    graph.v1.attendance_requirement = 99
    session.add(audit(graph))
    session.flush()
    session.rollback()
    assert session.query(AuditEvent).count() == 0
    assert session.get(PolicyVersion, graph.v1.id).attendance_requirement == 75


def test_audit_and_model_changes_share_transaction_commit(session, graph):
    graph.v1.attendance_requirement = 80
    session.add(audit(graph, before_state={'attendance_requirement': 75}, after_state={'attendance_requirement': 80}))
    session.commit()
    session.expire_all()
    assert graph.v1.attendance_requirement == 80
    assert session.query(AuditEvent).one().after_state == {'attendance_requirement': 80}


@pytest.mark.parametrize('kind', ['issue', 'review', 'index', 'audit'])
def test_referenced_core_records_cannot_be_silently_deleted(session, graph, kind):
    if kind in ('index', 'audit'):
        empty = PolicyVersion(family=graph.family, version='empty')
        session.add(empty)
        session.flush()
        graph.v1 = empty
        record = generation(graph) if kind == 'index' else audit(graph, rule_id=None, clause_id=None)
    else:
        record = {'issue': issue, 'review': review}[kind](graph)
    session.add(record)
    session.commit()
    statement = 'DELETE FROM rules WHERE id=:id' if kind in ('issue', 'review') else 'DELETE FROM policy_versions WHERE id=:id'
    target_id = graph.r1.id if kind in ('issue', 'review') else graph.v1.id
    with pytest.raises(IntegrityError):
        session.execute(text(statement), {'id': target_id})
        session.commit()
