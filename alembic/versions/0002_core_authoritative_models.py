"""Core authoritative records; preserve legacy values without inventing evidence.

Revision ID: 0002_core
Revises: 0001_initial

Requires an online database connection for legacy backfill. The existing
``policies`` rows become PolicyVersion records with their IDs/statuses intact.
Every migrated version requires source reingestion and every migrated Rule is
explicitly legacy/unverified. No source clauses or predecessor links are guessed.
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_core"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_context().as_sql:
        raise RuntimeError("0002_core requires an online connection for legacy backfill.")
    connection = op.get_bind()
    # Never silently choose which legacy current version to preserve.
    duplicate_current = connection.execute(sa.text(
        "SELECT 1 FROM policies WHERE status = 'CURRENT' GROUP BY name HAVING COUNT(*) > 1"
    )).first()
    invalid_status = connection.execute(sa.text(
        "SELECT 1 FROM policies WHERE status NOT IN ('DRAFT','VERIFIED','CURRENT','SUPERSEDED')"
    )).first()
    if duplicate_current or invalid_status:
        raise RuntimeError(
            "Legacy policy lifecycle conflicts require explicit reconciliation before "
            "migration; no statuses or source data have been changed."
        )

    op.create_table(
        "policy_families",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.UniqueConstraint("name", name="uq_policy_family_name"),
    )
    op.create_table(
        "policy_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("family_id", sa.Integer(), sa.ForeignKey("policy_families.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("attendance_requirement", sa.Float()),
        sa.Column("status", sa.String(), nullable=False, server_default="DRAFT"),
        sa.Column("requires_source_reingestion", sa.Boolean(), nullable=False, server_default=sa.text("1")),
        sa.Column("supersedes_version_id", sa.Integer()),
        sa.UniqueConstraint("family_id", "version", name="uq_policy_family_version"),
        sa.UniqueConstraint("family_id", "id", name="uq_policy_version_family_id"),
        sa.ForeignKeyConstraint(
            ["family_id", "supersedes_version_id"], ["policy_versions.family_id", "policy_versions.id"],
            name="fk_policy_version_predecessor_family", ondelete="RESTRICT",
        ),
        sa.CheckConstraint("supersedes_version_id IS NULL OR supersedes_version_id != id", name="ck_policy_version_not_self_predecessor"),
        sa.CheckConstraint("status IN ('DRAFT','VERIFIED','CURRENT','SUPERSEDED')", name="ck_policy_version_status"),
    )
    op.create_index("uq_policy_family_current", "policy_versions", ["family_id"], unique=True,
                    sqlite_where=sa.text("status = 'CURRENT'"), postgresql_where=sa.text("status = 'CURRENT'"))
    op.create_table(
        "clauses",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=False),
        sa.Column("start_offset", sa.Integer(), nullable=False),
        sa.Column("end_offset", sa.Integer(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("clause_label", sa.String()),
        sa.UniqueConstraint("version_id", "id", name="uq_clause_version_id"),
        sa.UniqueConstraint("version_id", "page_number", "start_offset", name="uq_clause_source_start"),
        sa.CheckConstraint("page_number >= 1", name="ck_clause_page_number"),
        sa.CheckConstraint("start_offset >= 0 AND end_offset > start_offset", name="ck_clause_offsets"),
        sa.CheckConstraint("length(source_text) = end_offset - start_offset", name="ck_clause_text_span"),
    )
    op.create_table(
        "rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("policy_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("source_clause_id", sa.Integer()),
        sa.Column("rule_type", sa.String(), nullable=False, server_default="ATTENDANCE_MINIMUM"),
        sa.Column("attendance_requirement", sa.Float()),
        sa.Column("legacy_unverified", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        sa.ForeignKeyConstraint(["version_id", "source_clause_id"], ["clauses.version_id", "clauses.id"],
                                name="fk_rule_clause_same_version", ondelete="RESTRICT"),
        sa.CheckConstraint("legacy_unverified = 1 OR source_clause_id IS NOT NULL", name="ck_rule_source_required"),
        sa.CheckConstraint("rule_type = 'ATTENDANCE_MINIMUM'", name="ck_rule_type"),
    )
    connection.execute(sa.text("INSERT INTO policy_families (name) SELECT DISTINCT name FROM policies ORDER BY name"))
    connection.execute(sa.text("""
        INSERT INTO policy_versions (id, family_id, version, attendance_requirement, status,
                                     requires_source_reingestion)
        SELECT p.id, f.id, p.version, p.attendance_requirement, p.status, 1
        FROM policies p JOIN policy_families f ON f.name = p.name
    """))
    connection.execute(sa.text("""
        INSERT INTO rules (id, version_id, rule_type, attendance_requirement, legacy_unverified)
        SELECT id, id, 'ATTENDANCE_MINIMUM', attendance_requirement, 1 FROM policies
    """))
    op.drop_table("policies")


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError("0002_core requires an online connection for safe downgrade.")
    connection = op.get_bind()
    # A legacy-only round trip is lossless. Refuse to discard newly authored
    # source data or relationships that the old schema cannot represent.
    has_new_data = any(connection.execute(sa.text(query)).first() for query in (
        "SELECT 1 FROM clauses LIMIT 1",
        "SELECT 1 FROM policy_versions WHERE supersedes_version_id IS NOT NULL OR requires_source_reingestion = 0 LIMIT 1",
        "SELECT 1 FROM rules r JOIN policy_versions v ON v.id = r.version_id "
        "WHERE r.legacy_unverified = 0 OR r.attendance_requirement IS NOT v.attendance_requirement LIMIT 1",
        "SELECT 1 FROM rules GROUP BY version_id HAVING COUNT(*) > 1",
        "SELECT 1 FROM policy_families f WHERE NOT EXISTS (SELECT 1 FROM policy_versions v WHERE v.family_id = f.id)",
    ))
    if has_new_data:
        raise RuntimeError("Downgrade would discard authoritative data; restore a pre-migration backup instead.")
    op.create_table(
        "policies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("attendance_requirement", sa.Float()),
        sa.Column("status", sa.String(), nullable=False),
        sa.UniqueConstraint("name", "version", name="uq_policy_name_version"),
    )
    connection.execute(sa.text("""
        INSERT INTO policies (id, name, version, attendance_requirement, status)
        SELECT v.id, f.name, v.version, v.attendance_requirement, v.status
        FROM policy_versions v JOIN policy_families f ON f.id = v.family_id
    """))
    op.drop_table("rules")
    op.drop_table("clauses")
    op.drop_index("uq_policy_family_current", table_name="policy_versions")
    op.drop_table("policy_versions")
    op.drop_table("policy_families")
