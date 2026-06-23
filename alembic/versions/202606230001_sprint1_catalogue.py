"""sprint 1 catalogue

Revision ID: 202606230001
Revises:
Create Date: 2026-06-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "202606230001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nom", sa.String(length=120), nullable=False),
        sa.Column("identifiant", sa.String(length=80), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_identifiant"), "users", ["identifiant"], unique=True)

    op.create_table(
        "catalogue_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code_element", sa.String(length=40), nullable=False),
        sa.Column("code_labo", sa.String(length=40), nullable=True),
        sa.Column("type", sa.String(length=40), nullable=False),
        sa.Column("nom", sa.String(length=255), nullable=False),
        sa.Column("service", sa.String(length=120), nullable=False),
        sa.Column("montant_fcfa", sa.Integer(), nullable=False),
        sa.Column("hopital_id", sa.String(length=80), nullable=False),
        sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("montant_fcfa >= 0", name="ck_catalogue_items_montant_positive"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_catalogue_items_actif"), "catalogue_items", ["actif"], unique=False)
    op.create_index(op.f("ix_catalogue_items_code_element"), "catalogue_items", ["code_element"], unique=True)
    op.create_index(op.f("ix_catalogue_items_code_labo"), "catalogue_items", ["code_labo"], unique=False)
    op.create_index(op.f("ix_catalogue_items_service"), "catalogue_items", ["service"], unique=False)
    op.create_index(op.f("ix_catalogue_items_type"), "catalogue_items", ["type"], unique=False)

    op.create_table(
        "catalogue_tariff_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("catalogue_item_id", sa.Integer(), nullable=False),
        sa.Column("ancien_montant_fcfa", sa.Integer(), nullable=False),
        sa.Column("nouveau_montant_fcfa", sa.Integer(), nullable=False),
        sa.Column("auteur_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["auteur_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["catalogue_item_id"], ["catalogue_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_catalogue_tariff_history_catalogue_item_id"),
        "catalogue_tariff_history",
        ["catalogue_item_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_catalogue_tariff_history_catalogue_item_id"), table_name="catalogue_tariff_history")
    op.drop_table("catalogue_tariff_history")
    op.drop_index(op.f("ix_catalogue_items_type"), table_name="catalogue_items")
    op.drop_index(op.f("ix_catalogue_items_service"), table_name="catalogue_items")
    op.drop_index(op.f("ix_catalogue_items_code_labo"), table_name="catalogue_items")
    op.drop_index(op.f("ix_catalogue_items_code_element"), table_name="catalogue_items")
    op.drop_index(op.f("ix_catalogue_items_actif"), table_name="catalogue_items")
    op.drop_table("catalogue_items")
    op.drop_index(op.f("ix_users_identifiant"), table_name="users")
    op.drop_table("users")
