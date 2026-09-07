"""Core policy records.

``Policy`` remains an alias for the version model while the existing API is
adapted in later checkpoints. ``attendance_requirement`` is the transitional
API value, not a validated or approved Rule. Legacy rows never acquire invented
source clauses during migration.
"""

from sqlalchemy import (
    Boolean, CheckConstraint, Column, Float, ForeignKey, ForeignKeyConstraint,
    Index, Integer, String, Text, UniqueConstraint, select, text,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import relationship

from database.db import Base

POLICY_STATUS_DRAFT = "DRAFT"
POLICY_STATUS_VERIFIED = "VERIFIED"
POLICY_STATUS_CURRENT = "CURRENT"
POLICY_STATUS_SUPERSEDED = "SUPERSEDED"
POLICY_STATUSES = (
    POLICY_STATUS_DRAFT, POLICY_STATUS_VERIFIED,
    POLICY_STATUS_CURRENT, POLICY_STATUS_SUPERSEDED,
)


class PolicyFamily(Base):
    __tablename__ = "policy_families"
    __table_args__ = (UniqueConstraint("name", name="uq_policy_family_name"),)

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    versions = relationship("PolicyVersion", back_populates="family", passive_deletes="all")
    audit_events = relationship("AuditEvent", back_populates="family", foreign_keys="AuditEvent.family_id", passive_deletes="all")


class PolicyVersion(Base):
    __tablename__ = "policy_versions"
    __table_args__ = (
        UniqueConstraint("family_id", "version", name="uq_policy_family_version"),
        UniqueConstraint("family_id", "id", name="uq_policy_version_family_id"),
        ForeignKeyConstraint(
            ["family_id", "supersedes_version_id"],
            ["policy_versions.family_id", "policy_versions.id"],
            name="fk_policy_version_predecessor_family", ondelete="RESTRICT",
        ),
        CheckConstraint("supersedes_version_id IS NULL OR supersedes_version_id != id",
                        name="ck_policy_version_not_self_predecessor"),
        CheckConstraint("status IN ('DRAFT','VERIFIED','CURRENT','SUPERSEDED')",
                        name="ck_policy_version_status"),
        Index("uq_policy_family_current", "family_id", unique=True,
              sqlite_where=text("status = 'CURRENT'"),
              postgresql_where=text("status = 'CURRENT'")),
    )

    id = Column(Integer, primary_key=True)
    family_id = Column(Integer, ForeignKey("policy_families.id", ondelete="RESTRICT"), nullable=False)
    version = Column(String, nullable=False)
    # Retained until every API rule write is routed through the rule service.
    attendance_requirement = Column(Float)
    status = Column(String, nullable=False, default=POLICY_STATUS_DRAFT, server_default="DRAFT")
    # True means provenance has not been established; status alone is not trust.
    requires_source_reingestion = Column(Boolean, nullable=False, default=True, server_default=text("1"))
    supersedes_version_id = Column(Integer)

    family = relationship("PolicyFamily", back_populates="versions", foreign_keys=[family_id])
    clauses = relationship("Clause", back_populates="version", passive_deletes="all")
    rules = relationship("Rule", back_populates="version", foreign_keys="Rule.version_id", passive_deletes="all")
    predecessor = relationship(
        "PolicyVersion", remote_side=[family_id, id],
        foreign_keys=[family_id, supersedes_version_id], viewonly=True,
    )

    validation_issues = relationship("ValidationIssue", back_populates="version", foreign_keys="ValidationIssue.version_id", passive_deletes="all")
    index_generations = relationship("IndexGeneration", back_populates="version", passive_deletes="all")
    audit_events = relationship(
        "AuditEvent", back_populates="version", foreign_keys="AuditEvent.version_id",
        primaryjoin="and_(AuditEvent.version_id == PolicyVersion.id, AuditEvent.family_id == PolicyVersion.family_id)",
        passive_deletes="all",
    )

    @hybrid_property
    def name(self):
        return self.family.name

    @name.expression
    def name(cls):
        return select(PolicyFamily.name).where(PolicyFamily.id == cls.family_id).scalar_subquery()


# Compatibility for existing imports and API queries, not a second data store.
Policy = PolicyVersion


class Clause(Base):
    __tablename__ = "clauses"
    __table_args__ = (
        UniqueConstraint("version_id", "id", name="uq_clause_version_id"),
        UniqueConstraint("version_id", "page_number", "start_offset", name="uq_clause_source_start"),
        CheckConstraint("page_number >= 1", name="ck_clause_page_number"),
        CheckConstraint("start_offset >= 0 AND end_offset > start_offset", name="ck_clause_offsets"),
        CheckConstraint("length(source_text) = end_offset - start_offset", name="ck_clause_text_span"),
    )

    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=False)
    page_number = Column(Integer, nullable=False)
    # Half-open Unicode character offsets in the original extracted page text.
    start_offset = Column(Integer, nullable=False)
    end_offset = Column(Integer, nullable=False)
    source_text = Column(Text, nullable=False)
    clause_label = Column(String)

    version = relationship("PolicyVersion", back_populates="clauses")
    rules = relationship(
        "Rule", back_populates="source_clause", foreign_keys="Rule.source_clause_id",
        primaryjoin="and_(Clause.id == Rule.source_clause_id, Clause.version_id == Rule.version_id)",
        passive_deletes="all",
    )


class Rule(Base):
    __tablename__ = "rules"
    __table_args__ = (
        Index("uq_rule_version_id", "version_id", "id", unique=True),
        ForeignKeyConstraint(
            ["version_id", "source_clause_id"], ["clauses.version_id", "clauses.id"],
            name="fk_rule_clause_same_version", ondelete="RESTRICT",
        ),
        CheckConstraint("legacy_unverified = 1 OR source_clause_id IS NOT NULL", name="ck_rule_source_required"),
        CheckConstraint("rule_type = 'ATTENDANCE_MINIMUM'", name="ck_rule_type"),
    )

    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=False)
    source_clause_id = Column(Integer)
    rule_type = Column(String, nullable=False, default="ATTENDANCE_MINIMUM", server_default="ATTENDANCE_MINIMUM")
    # No range constraint yet: preserve even invalid legacy values for review.
    attendance_requirement = Column(Float)
    legacy_unverified = Column(Boolean, nullable=False, default=False, server_default=text("0"))

    version = relationship("PolicyVersion", back_populates="rules", foreign_keys=[version_id])
    source_clause = relationship(
        "Clause", back_populates="rules",
        foreign_keys=[source_clause_id],
        primaryjoin="and_(Clause.id == Rule.source_clause_id, Clause.version_id == Rule.version_id)",
    )

    validation_issues = relationship(
        "ValidationIssue", back_populates="rule", foreign_keys="ValidationIssue.rule_id",
        primaryjoin="and_(ValidationIssue.rule_id == Rule.id, ValidationIssue.version_id == Rule.version_id)",
        passive_deletes="all",
    )
    review = relationship("RuleReview", back_populates="rule", uselist=False, passive_deletes="all")


# Register supporting tables in the same metadata used by the app and Alembic.
from database.supporting_models import AuditEvent, IndexGeneration, RuleReview, ValidationIssue  # noqa: E402,F401
