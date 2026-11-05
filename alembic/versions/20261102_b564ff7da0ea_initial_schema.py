"""initial schema

Revision ID: b564ff7da0ea
Revises:
Create Date: 2026-11-02 00:56:41.759904
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b564ff7da0ea"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Триграммы для нечёткого поиска товаров (индекс ix_products_name_trgm).
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=300), nullable=False),
        sa.Column("brand", sa.String(length=100), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=False),
        sa.Column("product_type", sa.String(length=100), nullable=True),
        sa.Column("package_amount", sa.Numeric(precision=10, scale=3), nullable=False),
        sa.Column(
            "package_unit",
            sa.Enum(
                "g",
                "ml",
                "pcs",
                "m",
                name="packageunit",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("package_amount > 0", name=op.f("ck_products_package_amount_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("external_id", name=op.f("uq_products_external_id")),
    )
    op.create_index(
        "ix_products_name_trgm",
        "products",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_table(
        "stores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("chain", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("address", sa.String(length=300), nullable=False),
        sa.Column("latitude", sa.Double(), nullable=False),
        sa.Column("longitude", sa.Double(), nullable=False),
        sa.Column(
            "format",
            sa.Enum(
                "convenience",
                "supermarket",
                "hypermarket",
                name="storeformat",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stores")),
        sa.UniqueConstraint("external_id", name=op.f("uq_stores_external_id")),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.Column(
            "role",
            sa.Enum(
                "user",
                "admin",
                name="userrole",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_table(
        "auth_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "provider",
            sa.Enum(
                "google",
                "apple",
                name="authprovider",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_auth_identities_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_identities")),
        sa.UniqueConstraint(
            "provider", "subject", name=op.f("uq_auth_identities_provider_subject")
        ),
    )
    op.create_index(
        op.f("ix_auth_identities_user_id"), "auth_identities", ["user_id"], unique=False
    )
    op.create_table(
        "carts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "saved",
                "completed",
                name="cartstatus",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_carts_owner_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_carts")),
    )
    op.create_index(op.f("ix_carts_owner_id"), "carts", ["owner_id"], unique=False)
    op.create_table(
        "catalog_imports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "archived",
                name="importstatus",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("timestamps_shifted", sa.Boolean(), nullable=False),
        sa.Column("stores_count", sa.Integer(), nullable=False),
        sa.Column("products_count", sa.Integer(), nullable=False),
        sa.Column("offers_count", sa.Integer(), nullable=False),
        sa.Column("rejected_rows_count", sa.Integer(), nullable=False),
        sa.Column("imported_by_id", sa.Uuid(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["imported_by_id"],
            ["users.id"],
            name=op.f("fk_catalog_imports_imported_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_catalog_imports")),
    )
    op.create_index(
        op.f("ix_catalog_imports_file_sha256"), "catalog_imports", ["file_sha256"], unique=False
    )
    op.create_index(
        "uq_catalog_imports_single_active",
        "catalog_imports",
        ["status"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "refresh_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("family_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_refresh_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_refresh_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_refresh_sessions_token_hash")),
    )
    op.create_index(
        op.f("ix_refresh_sessions_family_id"), "refresh_sessions", ["family_id"], unique=False
    )
    op.create_index(
        op.f("ix_refresh_sessions_user_id"), "refresh_sessions", ["user_id"], unique=False
    )
    op.create_table(
        "cart_items",
        sa.Column("cart_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.SmallInteger(), nullable=False),
        sa.Column(
            "added_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("quantity BETWEEN 1 AND 99", name=op.f("ck_cart_items_quantity_range")),
        sa.ForeignKeyConstraint(
            ["cart_id"], ["carts.id"], name=op.f("fk_cart_items_cart_id_carts"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_cart_items_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("cart_id", "product_id", name=op.f("pk_cart_items")),
    )
    op.create_table(
        "offers",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("import_id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("price_kopecks", sa.Integer(), nullable=False),
        sa.Column("card_price_kopecks", sa.Integer(), nullable=True),
        sa.Column("in_stock", sa.Boolean(), nullable=True),
        sa.Column("price_type", sa.String(length=20), nullable=True),
        sa.Column("price_conditions", sa.String(length=300), nullable=True),
        sa.Column("source_product_id", sa.String(length=100), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("card_price_kopecks > 0", name=op.f("ck_offers_card_price_positive")),
        sa.CheckConstraint("price_kopecks > 0", name=op.f("ck_offers_price_positive")),
        sa.ForeignKeyConstraint(
            ["import_id"],
            ["catalog_imports.id"],
            name=op.f("fk_offers_import_id_catalog_imports"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_offers_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"], name=op.f("fk_offers_store_id_stores"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_offers")),
        sa.UniqueConstraint(
            "import_id",
            "store_id",
            "product_id",
            name=op.f("uq_offers_import_id_store_id_product_id"),
        ),
    )
    op.create_index("ix_offers_import_product", "offers", ["import_id", "product_id"], unique=False)
    op.create_table(
        "plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("cart_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "planned",
                "active",
                "completed",
                name="planstatus",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("rank", sa.SmallInteger(), nullable=False),
        sa.Column("total_kopecks", sa.Integer(), nullable=False),
        sa.Column("savings_kopecks", sa.Integer(), nullable=True),
        sa.Column("walking_seconds", sa.Integer(), nullable=False),
        sa.Column("walking_meters", sa.Integer(), nullable=False),
        sa.Column("shopping_seconds", sa.Integer(), nullable=False),
        sa.Column("route_provider", sa.String(length=20), nullable=False),
        sa.Column("route_uses_road_network", sa.Boolean(), nullable=False),
        sa.Column("route_points", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("data_is_synthetic", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["cart_id"], ["carts.id"], name=op.f("fk_plans_cart_id_carts"), ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["users.id"], name=op.f("fk_plans_owner_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plans")),
    )
    op.create_index(op.f("ix_plans_cart_id"), "plans", ["cart_id"], unique=False)
    op.create_index(op.f("ix_plans_owner_id"), "plans", ["owner_id"], unique=False)
    op.create_index(
        "uq_plans_single_active_per_cart",
        "plans",
        ["cart_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_table(
        "plan_stops",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("subtotal_kopecks", sa.Integer(), nullable=False),
        sa.Column("shopping_seconds", sa.Integer(), nullable=False),
        sa.Column("walk_from_previous_seconds", sa.Integer(), nullable=False),
        sa.Column("walk_from_previous_meters", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["plan_id"], ["plans.id"], name=op.f("fk_plan_stops_plan_id_plans"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_plan_stops_store_id_stores"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_stops")),
        sa.UniqueConstraint("plan_id", "position", name=op.f("uq_plan_stops_plan_id_position")),
    )
    op.create_table(
        "plan_items",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("stop_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.SmallInteger(), nullable=False),
        sa.Column("unit_price_kopecks", sa.Integer(), nullable=False),
        sa.Column("card_price_kopecks", sa.Integer(), nullable=True),
        sa.Column("price_type", sa.String(length=20), nullable=True),
        sa.Column("price_conditions", sa.String(length=300), nullable=True),
        sa.Column("price_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "planned",
                "bought",
                "missing",
                name="planitemstatus",
                native_enum=False,
                create_constraint=True,
                length=20,
            ),
            nullable=False,
        ),
        sa.Column("alternative_store_id", sa.Integer(), nullable=True),
        sa.Column("alternative_price_kopecks", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["alternative_store_id"],
            ["stores.id"],
            name=op.f("fk_plan_items_alternative_store_id_stores"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_plan_items_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["stop_id"],
            ["plan_stops.id"],
            name=op.f("fk_plan_items_stop_id_plan_stops"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_items")),
    )


def downgrade() -> None:
    op.drop_table("plan_items")
    op.drop_table("plan_stops")
    op.drop_index(
        "uq_plans_single_active_per_cart",
        table_name="plans",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_index(op.f("ix_plans_owner_id"), table_name="plans")
    op.drop_index(op.f("ix_plans_cart_id"), table_name="plans")
    op.drop_table("plans")
    op.drop_index("ix_offers_import_product", table_name="offers")
    op.drop_table("offers")
    op.drop_table("cart_items")
    op.drop_index(op.f("ix_refresh_sessions_user_id"), table_name="refresh_sessions")
    op.drop_index(op.f("ix_refresh_sessions_family_id"), table_name="refresh_sessions")
    op.drop_table("refresh_sessions")
    op.drop_index(
        "uq_catalog_imports_single_active",
        table_name="catalog_imports",
        postgresql_where=sa.text("status = 'active'"),
    )
    op.drop_index(op.f("ix_catalog_imports_file_sha256"), table_name="catalog_imports")
    op.drop_table("catalog_imports")
    op.drop_index(op.f("ix_carts_owner_id"), table_name="carts")
    op.drop_table("carts")
    op.drop_index(op.f("ix_auth_identities_user_id"), table_name="auth_identities")
    op.drop_table("auth_identities")
    op.drop_table("users")
    op.drop_table("stores")
    op.drop_index(
        "ix_products_name_trgm",
        table_name="products",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.drop_table("products")
