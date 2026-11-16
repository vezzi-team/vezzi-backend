"""drop trigram search index

Revision ID: af7419366050
Revises: b564ff7da0ea
Create Date: 2026-11-16 20:17:43.141552
"""

from collections.abc import Sequence

from alembic import op

revision: str = "af7419366050"
down_revision: str | None = "b564ff7da0ea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Поиск товаров теперь делает ML-модуль (app/services/ml_matcher.py), индекс не нужен.
    op.drop_index("ix_products_name_trgm", table_name="products")


def downgrade() -> None:
    op.create_index(
        "ix_products_name_trgm",
        "products",
        ["name"],
        postgresql_ops={"name": "gin_trgm_ops"},
        postgresql_using="gin",
    )
