"""plan return walk

Revision ID: d764fe8d74f1
Revises: af7419366050
Create Date: 2026-11-16 21:11:57.900532
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d764fe8d74f1"
down_revision: str | None = "af7419366050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Обратный путь к старту по желанию пользователя. У старых планов его нет, поэтому NULL.
    op.add_column("plans", sa.Column("return_walk_seconds", sa.Integer(), nullable=True))
    op.add_column("plans", sa.Column("return_walk_meters", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("plans", "return_walk_meters")
    op.drop_column("plans", "return_walk_seconds")
