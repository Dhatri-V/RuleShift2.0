"""Supporting persistence only; no validation, review, indexing, or publication services.

Timestamps use UTC (SQLite CURRENT_TIMESTAMP). JSON snapshots are data supplied
by later services, never executed. No supporting rows imply no recorded result,
not approval or successful validation. Audit append-only protection targets SQLite.
"""
from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, DDL, ForeignKey,
    ForeignKeyConstraint, Index, Integer, JSON, String, Text, UniqueConstraint,
    event, func, text,
)
from sqlalchemy.orm import relationship

from database.db import Base


class ValidationIssue(Base):
    __tablename__ = "validation_issues"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "rule_id"], ["rules.version_id", "rules.id"],
            name="fk_validation_issue_rule_version", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["version_id", "clause_id"], ["clauses.version_id", "clauses.id"],
            name="fk_validation_issue_clause_version", ondelete="RESTRICT",
        ),
        CheckConstraint("length(trim(code)) > 0 AND length(trim(message)) > 0 AND length(trim(validator)) > 0",
                        name="ck_validation_issue_description"),
        CheckConstraint("severity IN ('ERROR','WARNING','INFO')", name="ck_validation_issue_severity"),
        CheckConstraint("is_blocking IN (0,1) AND (is_blocking = 0 OR severity = 'ERROR')",
                        name="ck_validation_issue_blocking"),
        CheckConstraint("status IN ('OPEN','RESOLVED')", name="ck_validation_issue_status"),
        CheckConstraint(
            "(status = 'OPEN' AND resolved_at IS NULL AND resolved_by IS NULL AND resolution_note IS NULL) OR "
            "(status = 'RESOLVED' AND resolved_at IS NOT NULL AND resolved_at >= created_at AND "
            "resolved_by IS NOT NULL AND length(trim(resolved_by)) > 0 AND "
            "resolution_note IS NOT NULL AND length(trim(resolution_note)) > 0)",
            name="ck_validation_issue_resolution",
        ),
        Index("ix_validation_issue_version_status", "version_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=False)
    rule_id = Column(Integer)
    clause_id = Column(Integer)
    code = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    validator = Column(String, nullable=False)
    severity = Column(String, nullable=False, default="ERROR", server_default="ERROR")
    is_blocking = Column(Boolean, nullable=False, default=True, server_default=text("1"))
    status = Column(String, nullable=False, default="OPEN", server_default="OPEN")
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    resolved_at = Column(DateTime)
    resolved_by = Column(String)
    resolution_note = Column(Text)

    version = relationship("PolicyVersion", back_populates="validation_issues", foreign_keys=[version_id])
    rule = relationship(
        "Rule", back_populates="validation_issues", foreign_keys=[rule_id],
        primaryjoin="and_(ValidationIssue.rule_id == Rule.id, ValidationIssue.version_id == Rule.version_id)",
    )
    clause = relationship(
        "Clause", foreign_keys=[clause_id],
        primaryjoin="and_(ValidationIssue.clause_id == Clause.id, ValidationIssue.version_id == Clause.version_id)",
    )


class RuleReview(Base):
    """Latest review metadata for a rule; no state transitions are performed here."""
    __tablename__ = "rule_reviews"
    __table_args__ = (
        UniqueConstraint("rule_id", name="uq_rule_review_rule"),
        CheckConstraint("status IN ('PENDING_REVIEW','APPROVED','REJECTED','NON_EXECUTABLE')",
                        name="ck_rule_review_status"),
        CheckConstraint(
            "(status = 'PENDING_REVIEW' AND reviewer_id IS NULL AND reviewed_at IS NULL AND reason IS NULL) OR "
            "(status != 'PENDING_REVIEW' AND reviewer_id IS NOT NULL AND length(trim(reviewer_id)) > 0 AND "
            "reviewed_at IS NOT NULL AND reviewed_at >= created_at AND "
            "reason IS NOT NULL AND length(trim(reason)) > 0 AND rule_snapshot IS NOT NULL)",
            name="ck_rule_review_metadata",
        ),
    )

    id = Column(Integer, primary_key=True)
    rule_id = Column(Integer, ForeignKey("rules.id", ondelete="RESTRICT"), nullable=False)
    status = Column(String, nullable=False, default="PENDING_REVIEW", server_default="PENDING_REVIEW")
    reviewer_id = Column(String)
    reviewed_at = Column(DateTime)
    reason = Column(Text)
    rule_snapshot = Column(JSON(none_as_null=True))
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())

    rule = relationship("Rule", back_populates="review")


class IndexGeneration(Base):
    """Recorded indexing attempt/configuration, not proof that Chroma was checked."""
    __tablename__ = "index_generations"
    __table_args__ = (
        UniqueConstraint("version_id", "generation", name="uq_index_generation_version_number"),
        CheckConstraint("generation >= 1 AND typeof(generation) = 'integer'", name="ck_index_generation_number"),
        CheckConstraint("status IN ('PENDING','BUILDING','READY','FAILED')", name="ck_index_generation_status"),
        CheckConstraint("expected_chunk_count >= 0 AND typeof(expected_chunk_count) = 'integer' AND "
                        "(observed_chunk_count IS NULL OR (observed_chunk_count >= 0 AND typeof(observed_chunk_count) = 'integer'))",
                        name="ck_index_generation_counts"),
        CheckConstraint("length(trim(collection_name)) > 0 AND length(trim(embedding_model)) > 0",
                        name="ck_index_generation_configuration"),
        CheckConstraint("manifest_sha256 IS NULL OR (length(manifest_sha256) = 64 AND manifest_sha256 NOT GLOB '*[^0-9a-f]*')",
                        name="ck_index_generation_manifest_hash"),
        CheckConstraint("completed_at IS NULL OR completed_at >= created_at", name="ck_index_generation_time"),
        Index("ix_index_generation_version_status", "version_id", "status"),
    )

    id = Column(Integer, primary_key=True)
    version_id = Column(Integer, ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=False)
    generation = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="PENDING", server_default="PENDING")
    collection_name = Column(String, nullable=False)
    embedding_model = Column(String, nullable=False)
    chunking_config = Column(JSON(none_as_null=True), nullable=False)
    expected_chunk_count = Column(Integer, nullable=False, default=0, server_default=text("0"))
    observed_chunk_count = Column(Integer)
    manifest_sha256 = Column(String(64))
    failure_detail = Column(Text)
    created_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())
    completed_at = Column(DateTime)

    version = relationship("PolicyVersion", back_populates="index_generations")


class AuditEvent(Base):
    """Append-only event payload; later services must populate/redact it atomically."""
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint("id > 0", name="ck_audit_event_positive_id"),
        ForeignKeyConstraint(
            ["family_id", "version_id"], ["policy_versions.family_id", "policy_versions.id"],
            name="fk_audit_event_version_family", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["version_id", "rule_id"], ["rules.version_id", "rules.id"],
            name="fk_audit_event_rule_version", ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["version_id", "clause_id"], ["clauses.version_id", "clauses.id"],
            name="fk_audit_event_clause_version", ondelete="RESTRICT",
        ),
        CheckConstraint("version_id IS NOT NULL OR (rule_id IS NULL AND clause_id IS NULL)", name="ck_audit_event_target"),
        CheckConstraint("actor_type IN ('ADMIN','SYSTEM')", name="ck_audit_event_actor_type"),
        CheckConstraint("length(trim(actor_id)) > 0 AND length(trim(action)) > 0", name="ck_audit_event_identity"),
        Index("ix_audit_event_family_time", "family_id", "occurred_at"),
        Index("ix_audit_event_version_time", "version_id", "occurred_at"),
    )

    id = Column(Integer, primary_key=True)
    family_id = Column(Integer, ForeignKey("policy_families.id", ondelete="RESTRICT"), nullable=False)
    version_id = Column(Integer)
    rule_id = Column(Integer)
    clause_id = Column(Integer)
    actor_type = Column(String, nullable=False)
    actor_id = Column(String, nullable=False)
    action = Column(String, nullable=False)
    reason = Column(Text)
    before_state = Column(JSON(none_as_null=True))
    after_state = Column(JSON(none_as_null=True))
    correlation_id = Column(String)
    occurred_at = Column(DateTime, nullable=False, server_default=func.current_timestamp())

    family = relationship("PolicyFamily", back_populates="audit_events", foreign_keys=[family_id])
    version = relationship(
        "PolicyVersion", back_populates="audit_events", foreign_keys=[version_id],
        primaryjoin="and_(AuditEvent.version_id == PolicyVersion.id, AuditEvent.family_id == PolicyVersion.family_id)",
    )
    rule = relationship(
        "Rule", foreign_keys=[rule_id],
        primaryjoin="and_(AuditEvent.rule_id == Rule.id, AuditEvent.version_id == Rule.version_id)",
    )
    clause = relationship(
        "Clause", foreign_keys=[clause_id],
        primaryjoin="and_(AuditEvent.clause_id == Clause.id, AuditEvent.version_id == Clause.version_id)",
    )


# Enforce append-only history for raw SQL as well as ORM writes. Migration 0003
# contains its own frozen DDL so historical migrations never import live models.
for operation in ("UPDATE", "DELETE"):
    event.listen(
        AuditEvent.__table__, "after_create",
        DDL(f"CREATE TRIGGER audit_events_no_{operation.lower()} BEFORE {operation} ON audit_events "
            "BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END").execute_if(dialect="sqlite"),
    )

# SQLite REPLACE can bypass DELETE triggers unless recursive_triggers is enabled.
event.listen(
    AuditEvent.__table__, "after_create",
    DDL("CREATE TRIGGER audit_events_no_replace BEFORE INSERT ON audit_events "
        "WHEN EXISTS (SELECT 1 FROM audit_events WHERE id = NEW.id) "
        "BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END").execute_if(dialect="sqlite"),
)
