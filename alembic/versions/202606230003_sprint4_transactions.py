"""sprint 4 transactions

Revision ID: 202606230003
Revises: 202606230002
Create Date: 2026-06-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "202606230003"
down_revision: Union[str, None] = "202606230002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "transactions" not in tables:
        op.create_table(
            "transactions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("visit_id", sa.Integer(), nullable=False),
            sa.Column("caisse_id", sa.Integer(), nullable=True),
            sa.Column("caissier_id", sa.Integer(), nullable=False),
            sa.Column("statut", sa.String(length=32), nullable=False),
            sa.Column("montant_total_fcfa", sa.Integer(), nullable=False),
            sa.Column("montant_encaisse_fcfa", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["caissier_id"], ["users.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["caisse_id"], ["caisses.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["visit_id"], ["visits.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("visit_id", name="uq_transactions_visit_id"),
        )
        op.create_index(op.f("ix_transactions_statut"), "transactions", ["statut"], unique=False)

    if "transaction_lines" not in tables:
        op.create_table(
            "transaction_lines",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("transaction_id", sa.Integer(), nullable=False),
            sa.Column("catalogue_item_id", sa.Integer(), nullable=False),
            sa.Column("code_element_snapshot", sa.String(length=40), nullable=False),
            sa.Column("nom_snapshot", sa.String(length=255), nullable=False),
            sa.Column("type_snapshot", sa.String(length=40), nullable=False),
            sa.Column("service_snapshot", sa.String(length=120), nullable=False),
            sa.Column("quantite", sa.Integer(), nullable=False),
            sa.Column("prix_unitaire_fcfa", sa.Integer(), nullable=False),
            sa.Column("montant_ligne_fcfa", sa.Integer(), nullable=False),
            sa.Column("payable", sa.Boolean(), nullable=False),
            sa.Column("motif_non_honore", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["catalogue_item_id"], ["catalogue_items.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )

    if "payments" not in tables:
        op.create_table(
            "payments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("transaction_id", sa.Integer(), nullable=False),
            sa.Column("moyen_paiement", sa.String(length=32), nullable=False),
            sa.Column("statut", sa.String(length=32), nullable=False),
            sa.Column("montant_fcfa", sa.Integer(), nullable=False),
            sa.Column("reference_paiement", sa.String(length=120), nullable=True),
            sa.Column("telephone_paiement", sa.String(length=32), nullable=True),
            sa.Column("cheque_numero", sa.String(length=120), nullable=True),
            sa.Column("cheque_banque", sa.String(length=120), nullable=True),
            sa.Column("cheque_titulaire", sa.String(length=120), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("transaction_id"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "payments" in tables:
        op.drop_table("payments")

    if "transaction_lines" in tables:
        op.drop_table("transaction_lines")

    if "transactions" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("transactions")}
        if op.f("ix_transactions_statut") in indexes:
            op.drop_index(op.f("ix_transactions_statut"), table_name="transactions")
        op.drop_table("transactions")
