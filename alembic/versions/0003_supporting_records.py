"""Supporting persistence only: validation, review, index metadata, audit events.

Revision ID: 0003_supporting
Revises: 0002_core

Additive SQLite migration. No legacy approvals/results are inferred, and no
publication/indexing behavior is introduced. Downgrade refuses to discard records.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_supporting"
down_revision = "0002_core"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("uq_rule_version_id", "rules", ["version_id", "id"], unique=True)
    op.create_table(
        "validation_issues",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("rule_id", sa.Integer()),
        sa.Column("clause_id", sa.Integer()),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("validator", sa.String(), nullable=False),
        sa.Column("severity", sa.String(), nullable=False, server_default="ERROR"),
        sa.Column("is_blocking", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("status", sa.String(), nullable=False, server_default="OPEN"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("resolved_at", sa.DateTime()),
        sa.Column("resolved_by", sa.String()),
        sa.Column("resolution_note", sa.Text()),
        sa.ForeignKeyConstraint(["version_id", "rule_id"], ["rules.version_id", "rules.id"], name="fk_validation_issue_rule_version", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["version_id", "clause_id"], ["clauses.version_id", "clauses.id"], name="fk_validation_issue_clause_version", ondelete="RESTRICT"),
        sa.CheckConstraint("length(trim(code)) > 0 AND length(trim(message)) > 0 AND length(trim(validator)) > 0", name="ck_validation_issue_description"),
        sa.CheckConstraint("severity IN ('ERROR','WARNING','INFO')", name="ck_validation_issue_severity"),
        sa.CheckConstraint("is_blocking IN (0,1) AND (is_blocking = 0 OR severity = 'ERROR')", name="ck_validation_issue_blocking"),
        sa.CheckConstraint("status IN ('OPEN','RESOLVED')", name="ck_validation_issue_status"),
        sa.CheckConstraint(
            "(status = 'OPEN' AND resolved_at IS NULL AND resolved_by IS NULL AND resolution_note IS NULL) OR "
            "(status = 'RESOLVED' AND resolved_at IS NOT NULL AND resolved_at >= created_at AND "
            "resolved_by IS NOT NULL AND length(trim(resolved_by)) > 0 AND "
            "resolution_note IS NOT NULL AND length(trim(resolution_note)) > 0)", name="ck_validation_issue_resolution",
        ),
    )
    op.create_index("ix_validation_issue_version_status", "validation_issues", ["version_id", "status"])
    op.create_table(
        "rule_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("rule_id", sa.Integer(), sa.ForeignKey("rules.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDING_REVIEW"),
        sa.Column("reviewer_id", sa.String()),
        sa.Column("reviewed_at", sa.DateTime()),
        sa.Column("reason", sa.Text()),
        sa.Column("rule_snapshot", sa.JSON(none_as_null=True)),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.UniqueConstraint("rule_id", name="uq_rule_review_rule"),
        sa.CheckConstraint("status IN ('PENDING_REVIEW','APPROVED','REJECTED','NON_EXECUTABLE')", name="ck_rule_review_status"),
        sa.CheckConstraint(
            "(status = 'PENDING_REVIEW' AND reviewer_id IS NULL AND reviewed_at IS NULL AND reason IS NULL) OR "
            "(status != 'PENDING_REVIEW' AND reviewer_id IS NOT NULL AND length(trim(reviewer_id)) > 0 AND "
            "reviewed_at IS NOT NULL AND reviewed_at >= created_at AND "
            "reason IS NOT NULL AND length(trim(reason)) > 0 AND rule_snapshot IS NOT NULL)", name="ck_rule_review_metadata",
        ),
    )
    op.create_table(
        "index_generations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
        sa.Column("collection_name", sa.String(), nullable=False),
        sa.Column("embedding_model", sa.String(), nullable=False),
        sa.Column("chunking_config", sa.JSON(none_as_null=True), nullable=False),
        sa.Column("expected_chunk_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("observed_chunk_count", sa.Integer()),
        sa.Column("manifest_sha256", sa.String(64)),
        sa.Column("failure_detail", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.Column("completed_at", sa.DateTime()),
        sa.UniqueConstraint("version_id", "generation", name="uq_index_generation_version_number"),
        sa.CheckConstraint("generation >= 1 AND typeof(generation) = 'integer'", name="ck_index_generation_number"),
        sa.CheckConstraint("status IN ('PENDING','BUILDING','READY','FAILED')", name="ck_index_generation_status"),
        sa.CheckConstraint("expected_chunk_count >= 0 AND typeof(expected_chunk_count) = 'integer' AND "
                           "(observed_chunk_count IS NULL OR (observed_chunk_count >= 0 AND typeof(observed_chunk_count) = 'integer'))", name="ck_index_generation_counts"),
        sa.CheckConstraint("length(trim(collection_name)) > 0 AND length(trim(embedding_model)) > 0", name="ck_index_generation_configuration"),
        sa.CheckConstraint("manifest_sha256 IS NULL OR (length(manifest_sha256) = 64 AND manifest_sha256 NOT GLOB '*[^0-9a-f]*')", name="ck_index_generation_manifest_hash"),
        sa.CheckConstraint("completed_at IS NULL OR completed_at >= created_at", name="ck_index_generation_time"),
    )
    op.create_index("ix_index_generation_version_status", "index_generations", ["version_id", "status"])
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("policy_families.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version_id", sa.Integer()),
        sa.Column("rule_id", sa.Integer()),
        sa.Column("clause_id", sa.Integer()),
        sa.Column("actor_type", sa.String(), nullable=False),
        sa.Column("actor_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("reason", sa.Text()),
        sa.Column("before_state", sa.JSON(none_as_null=True)),
        sa.Column("after_state", sa.JSON(none_as_null=True)),
        sa.Column("correlation_id", sa.String()),
        sa.Column("occurred_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.ForeignKeyConstraint(["family_id", "version_id"], ["policy_versions.family_id", "policy_versions.id"], name="fk_audit_event_version_family", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["version_id", "rule_id"], ["rules.version_id", "rules.id"], name="fk_audit_event_rule_version", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["version_id", "clause_id"], ["clauses.version_id", "clauses.id"], name="fk_audit_event_clause_version", ondelete="RESTRICT"),
        sa.CheckConstraint("id > 0", name="ck_audit_event_positive_id"),
        sa.CheckConstraint("version_id IS NOT NULL OR (rule_id IS NULL AND clause_id IS NULL)", name="ck_audit_event_target"),
        sa.CheckConstraint("actor_type IN ('ADMIN','SYSTEM')", name="ck_audit_event_actor_type"),
        sa.CheckConstraint("length(trim(actor_id)) > 0 AND length(trim(action)) > 0", name="ck_audit_event_identity"),
    )
    op.create_index("ix_audit_event_family_time", "audit_events", ["family_id", "occurred_at"])
    op.create_index("ix_audit_event_version_time", "audit_events", ["version_id", "occurred_at"])
    for operation in ("UPDATE", "DELETE"):
        op.execute(f"CREATE TRIGGER audit_events_no_{operation.lower()} BEFORE {operation} ON audit_events "
                   "BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END")
    op.execute("CREATE TRIGGER audit_events_no_replace BEFORE INSERT ON audit_events "
               "WHEN EXISTS (SELECT 1 FROM audit_events WHERE id = NEW.id) "
               "BEGIN SELECT RAISE(ABORT, 'audit events are append-only'); END")


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError("0003_supporting downgrade requires an online connection to protect supporting records.")
    connection = op.get_bind()
    tables = ("audit_events", "index_generations", "rule_reviews", "validation_issues")
    if any(connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() for table in tables):
        raise RuntimeError("Downgrade would discard supporting records; retain/export them or restore a pre-migration backup.")
    for operation in ("update", "delete", "replace"):
        op.execute(f"DROP TRIGGER audit_events_no_{operation}")
    for table in tables:
        op.drop_table(table)
    op.drop_index("uq_rule_version_id", table_name="rules")
