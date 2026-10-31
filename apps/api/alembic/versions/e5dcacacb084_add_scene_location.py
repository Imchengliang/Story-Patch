"""add scene location

Revision ID: e5dcacacb084
Revises: 25eb339ea4af
Create Date: 2026-10-28 14:05:50.902243

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e5dcacacb084"
down_revision: str | None = "25eb339ea4af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("scenes", sa.Column("location", sa.String(length=200), nullable=True))


def downgrade() -> None:
    op.drop_column("scenes", "location")
