"""Initial RuleShift schema: policies table.

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-09

Represents the schema that existed before Alembic was introduced, so that
running `alembic upgrade head` on a fresh database produces exactly the
same tables and constraints the app has always used. Existing databases
keep their data; Alembic only records the baseline.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("version", sa.String(), nullable=False),
        sa.Column("attendance_requirement", sa.Float(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", "version", name="uq_policy_name_version"),
    )


def downgrade() -> None:
    op.drop_table("policies")