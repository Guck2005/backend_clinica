"""sprint 5 fedapay mobile money

Revision ID: 202606230004
Revises: 202606230003
Create Date: 2026-06-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "202606230004"
down_revision: Union[str, None] = "202606230003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_new_payments_table(name: str) -> None:
    op.create_table(
        name,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("moyen_paiement", sa.String(length=32), nullable=False),
        sa.Column("statut", sa.String(length=32), nullable=False),
        sa.Column("montant_fcfa", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("provider_attempt_id", sa.String(length=120), nullable=True),
        sa.Column("provider_status", sa.String(length=64), nullable=True),
        sa.Column("operator_code", sa.String(length=32), nullable=True),
        sa.Column("reference_paiement", sa.String(length=120), nullable=True),
        sa.Column("telephone_paiement", sa.String(length=32), nullable=True),
        sa.Column("cheque_numero", sa.String(length=120), nullable=True),
        sa.Column("cheque_banque", sa.String(length=120), nullable=True),
        sa.Column("cheque_titulaire", sa.String(length=120), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "payments" not in tables:
        _create_new_payments_table("payments")
        op.create_index("ix_payments_provider_attempt_id", "payments", ["provider_attempt_id"], unique=False)
        return

    columns = {column["name"] for column in inspector.get_columns("payments")}
    indexes = {index["name"] for index in inspector.get_indexes("payments")}

    if "attempt_no" in columns:
        if "ix_payments_provider_attempt_id" not in indexes:
            op.create_index("ix_payments_provider_attempt_id", "payments", ["provider_attempt_id"], unique=False)
        return

    _create_new_payments_table("payments_new")
    op.execute(
        """
        INSERT INTO payments_new (
            id,
            transaction_id,
            attempt_no,
            moyen_paiement,
            statut,
            montant_fcfa,
            provider,
            provider_attempt_id,
            provider_status,
            operator_code,
            reference_paiement,
            telephone_paiement,
            cheque_numero,
            cheque_banque,
            cheque_titulaire,
            raw_payload,
            created_at,
            updated_at,
            confirmed_at,
            failed_at
        )
        SELECT
            id,
            transaction_id,
            1,
            moyen_paiement,
            statut,
            montant_fcfa,
            NULL,
            NULL,
            NULL,
            NULL,
            reference_paiement,
            telephone_paiement,
            cheque_numero,
            cheque_banque,
            cheque_titulaire,
            NULL,
            created_at,
            created_at,
            CASE WHEN statut = 'CONFIRME' THEN created_at ELSE NULL END,
            NULL
        FROM payments
        """
    )
    op.drop_table("payments")
    op.rename_table("payments_new", "payments")
    op.create_index("ix_payments_provider_attempt_id", "payments", ["provider_attempt_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "payments" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("payments")}
    if "attempt_no" not in columns:
        return

    op.create_table(
        "payments_old",
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
    op.execute(
        """
        INSERT INTO payments_old (
            id,
            transaction_id,
            moyen_paiement,
            statut,
            montant_fcfa,
            reference_paiement,
            telephone_paiement,
            cheque_numero,
            cheque_banque,
            cheque_titulaire,
            created_at
        )
        SELECT
            id,
            transaction_id,
            moyen_paiement,
            statut,
            montant_fcfa,
            reference_paiement,
            telephone_paiement,
            cheque_numero,
            cheque_banque,
            cheque_titulaire,
            created_at
        FROM payments
        WHERE attempt_no = 1
        """
    )
    indexes = {index["name"] for index in inspector.get_indexes("payments")}
    if "ix_payments_provider_attempt_id" in indexes:
        op.drop_index("ix_payments_provider_attempt_id", table_name="payments")
    op.drop_table("payments")
    op.rename_table("payments_old", "payments")

