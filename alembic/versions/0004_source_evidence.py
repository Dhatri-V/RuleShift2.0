"""Persist original PDFs and extracted pages; preserve all existing versions."""
from alembic import op
import sqlalchemy as sa

revision = "0004_source"
down_revision = "0003_supporting"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "source_documents",
        sa.Column("version_id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("policy_id", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("pdf_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("byte_count", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("parser", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["policy_id", "version_id"], ["policy_versions.family_id", "policy_versions.id"],
                                ondelete="RESTRICT", name="fk_source_version_owner"),
        sa.CheckConstraint("length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'", name="ck_source_sha256"),
        sa.CheckConstraint("byte_count > 0 AND length(pdf_bytes) = byte_count", name="ck_source_bytes"),
        sa.CheckConstraint("page_count > 0", name="ck_source_pages"),
    )
    op.create_table(
        "source_pages",
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("source_documents.version_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("page_number", sa.Integer(), primary_key=True),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.CheckConstraint("page_number >= 1", name="ck_source_page_number"),
    )
    for table, key in (("source_documents", "version_id = NEW.version_id"),
                       ("source_pages", "version_id = NEW.version_id AND page_number = NEW.page_number")):
        op.execute(f"CREATE TRIGGER {table}_no_update BEFORE UPDATE ON {table} "
                   "BEGIN SELECT RAISE(ABORT, 'source evidence is immutable'); END")
        op.execute(f"CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table} "
                   f"WHEN EXISTS (SELECT 1 FROM {table} WHERE {key}) "
                   "BEGIN SELECT RAISE(ABORT, 'source evidence is immutable'); END")


def downgrade():
    if op.get_context().as_sql:
        raise RuntimeError("Source downgrade requires online data-preservation checks")
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM source_documents")):
        raise RuntimeError("Cannot discard source evidence; restore a backup instead")
    op.drop_table("source_pages")
    op.drop_table("source_documents")
