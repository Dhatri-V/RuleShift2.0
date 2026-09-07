"""Checkpoint 1A: relational invariants, not review/publication services."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database.db import Base
from database.models import Clause, Policy, PolicyFamily, PolicyVersion, Rule


@pytest.fixture
def session():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def version(session, label='v1', family=None, status='DRAFT'):
    item = PolicyVersion(family=family or PolicyFamily(name='Attendance'), version=label, status=status)
    session.add(item)
    session.flush()
    return item


def clause(session, parent, **overrides):
    values = dict(version=parent, page_number=3, start_offset=10,
                  end_offset=25, source_text='Attendance 85%.', clause_label='4.2')
    values.update(overrides)
    item = Clause(**values)
    session.add(item)
    session.flush()
    return item


def test_authoritative_relationships_and_unicode_source_round_trip(session):
    old = version(session)
    new = version(session, 'v2', old.family)
    new.supersedes_version_id = old.id
    source = clause(session, new, source_text='Présence ≥ 85%.', end_offset=25)
    rule = Rule(version=new, source_clause=source, attendance_requirement=85)
    session.add(rule)
    session.commit()
    session.expire_all()
    assert Policy is PolicyVersion
    assert new.family.versions == [old, new]
    assert new.predecessor.id == old.id
    assert new.clauses[0].source_text == 'Présence ≥ 85%.'
    assert new.clauses[0].page_number == 3
    assert new.rules[0].source_clause.id == source.id
    assert source.rules[0].id == rule.id
    assert session.query(Policy).filter(Policy.name == 'Attendance').count() == 2
    assert new.requires_source_reingestion is True


def test_foreign_keys_are_enabled(session):
    assert session.scalar(text('PRAGMA foreign_keys')) == 1
    session.add(PolicyVersion(family_id=999, version='v1'))
    with pytest.raises(IntegrityError):
        session.flush()


def test_family_name_unique(session):
    session.add_all([PolicyFamily(name='Same'), PolicyFamily(name='Same')])
    with pytest.raises(IntegrityError):
        session.flush()


def test_version_label_unique_within_family(session):
    first = version(session)
    with pytest.raises(IntegrityError):
        version(session, 'v1', first.family)


def test_same_label_allowed_for_different_families(session):
    version(session)
    version(session, family=PolicyFamily(name='Scholarship'))
    session.commit()
    assert session.query(PolicyVersion).count() == 2


def test_one_current_version_per_family(session):
    first = version(session, status='CURRENT')
    with pytest.raises(IntegrityError):
        version(session, 'v2', first.family, 'CURRENT')


def test_different_families_can_each_have_current_version(session):
    version(session, status='CURRENT')
    version(session, family=PolicyFamily(name='Scholarship'), status='CURRENT')
    session.commit()


@pytest.mark.parametrize('predecessor', ['self', 'foreign', 'missing'])
def test_predecessor_must_exist_in_same_family_and_not_be_self(session, predecessor):
    first = version(session)
    other = version(session, family=PolicyFamily(name='Other'))
    first.supersedes_version_id = {'self': first.id, 'foreign': other.id, 'missing': 999}[predecessor]
    with pytest.raises(IntegrityError):
        session.flush()


@pytest.mark.parametrize('overrides', [
    {'page_number': 0}, {'start_offset': -1}, {'end_offset': 10},
    {'end_offset': 99}, {'source_text': ''},
])
def test_invalid_clause_positions_or_text_are_rejected(session, overrides):
    parent = version(session)
    with pytest.raises(IntegrityError):
        clause(session, parent, **overrides)


def test_duplicate_clause_source_position_rejected(session):
    parent = version(session)
    clause(session, parent)
    with pytest.raises(IntegrityError):
        clause(session, parent)


def test_rule_cannot_reference_another_versions_clause(session):
    first = version(session)
    second = version(session, 'v2', first.family)
    source = clause(session, first)
    session.add(Rule(version=second, source_clause_id=source.id, attendance_requirement=85))
    with pytest.raises(IntegrityError):
        session.flush()


def test_nonlegacy_rule_requires_source(session):
    parent = version(session)
    session.add(Rule(version=parent, attendance_requirement=85))
    with pytest.raises(IntegrityError):
        session.flush()


def test_legacy_rule_preserves_invalid_value_without_fabricating_source(session):
    parent = version(session)
    session.add(Rule(version=parent, attendance_requirement=110, legacy_unverified=True))
    session.commit()
    rule = parent.rules[0]
    assert rule.attendance_requirement == 110
    assert rule.source_clause is None
    assert rule.legacy_unverified is True


def test_cited_clause_cannot_be_deleted(session):
    parent = version(session)
    source = clause(session, parent)
    session.add(Rule(version=parent, source_clause_id=source.id, attendance_requirement=85))
    session.commit()
    session.delete(source)
    with pytest.raises(IntegrityError):
        session.flush()


def test_family_with_versions_cannot_be_deleted(session):
    parent = version(session)
    session.commit()
    session.delete(parent.family)
    with pytest.raises(IntegrityError):
        session.flush()


def test_invalid_status_is_rejected(session):
    with pytest.raises(IntegrityError):
        version(session, status='UNKNOWN')


def test_relationship_assignment_cannot_reparent_rule_to_foreign_source(session):
    first = version(session)
    second = version(session, 'v2', first.family)
    source = clause(session, first)
    session.add(Rule(version=second, source_clause=source, attendance_requirement=85))
    with pytest.raises(IntegrityError):
        session.flush()
