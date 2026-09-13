"""Immutable deterministic attendance impact snapshots.

Revision ID: 0005_impact
Revises: 0004_source
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_impact"
down_revision = "0004_source"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "impact_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("old_version_id", sa.Integer(), sa.ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("new_version_id", sa.Integer(), sa.ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("attendance", sa.Float(), nullable=False),
        sa.Column("old_rule_snapshot", sa.JSON(), nullable=False),
        sa.Column("new_rule_snapshot", sa.JSON(), nullable=False),
        sa.Column("old_result", sa.String(), nullable=False),
        sa.Column("new_result", sa.String(), nullable=False),
        sa.Column("impact", sa.String(), nullable=False),
        sa.Column("engine_version", sa.String(), nullable=False, server_default="attendance-v1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp()),
        sa.CheckConstraint("attendance >= 0 AND attendance <= 100", name="ck_impact_attendance"),
        sa.CheckConstraint("length(trim(impact)) > 0", name="ck_impact_result"),
        sa.CheckConstraint("old_version_id != new_version_id", name="ck_impact_distinct_versions"),
    )
    op.execute("CREATE TRIGGER impact_runs_no_update BEFORE UPDATE ON impact_runs BEGIN SELECT RAISE(ABORT, 'impact history is immutable'); END")
    op.execute("CREATE TRIGGER impact_runs_no_delete BEFORE DELETE ON impact_runs BEGIN SELECT RAISE(ABORT, 'impact history is immutable'); END")


def downgrade():
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM impact_runs")).scalar_one()
    if count:
        raise RuntimeError("Refusing to discard immutable impact history during downgrade")
    op.execute("DROP TRIGGER IF EXISTS impact_runs_no_delete")
    op.execute("DROP TRIGGER IF EXISTS impact_runs_no_update")
    op.drop_table("impact_runs")
