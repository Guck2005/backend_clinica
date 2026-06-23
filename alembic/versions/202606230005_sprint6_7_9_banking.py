"""sprint 6 7 9 banking

Revision ID: 202606230005
Revises: 202606230004
Create Date: 2026-06-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "202606230005"
down_revision: Union[str, None] = "202606230004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "factures" not in tables:
        op.create_table(
            "factures",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("numero_facture", sa.String(length=32), nullable=False),
            sa.Column("transaction_id", sa.Integer(), nullable=False),
            sa.Column("id_visite_snapshot", sa.String(length=20), nullable=False),
            sa.Column("patient_nom_snapshot", sa.String(length=160), nullable=False),
            sa.Column("patient_tel_snapshot", sa.String(length=32), nullable=False),
            sa.Column("moyen_paiement_snapshot", sa.String(length=32), nullable=False),
            sa.Column("reference_snapshot", sa.String(length=120), nullable=True),
            sa.Column("statut_document", sa.String(length=64), nullable=False),
            sa.Column("mention_paiement", sa.String(length=255), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("numero_facture", name="uq_factures_numero_facture"),
            sa.UniqueConstraint("transaction_id", name="uq_factures_transaction_id"),
        )
        op.create_index(op.f("ix_factures_numero_facture"), "factures", ["numero_facture"], unique=False)
        op.create_index(op.f("ix_factures_id_visite_snapshot"), "factures", ["id_visite_snapshot"], unique=False)
        op.create_index(op.f("ix_factures_moyen_paiement_snapshot"), "factures", ["moyen_paiement_snapshot"], unique=False)
        op.create_index(op.f("ix_factures_statut_document"), "factures", ["statut_document"], unique=False)

    if "alertes" not in tables:
        op.create_table(
            "alertes",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("rule_code", sa.String(length=16), nullable=False),
            sa.Column("gravite", sa.String(length=16), nullable=False),
            sa.Column("message", sa.String(length=255), nullable=False),
            sa.Column("caisse_id", sa.Integer(), nullable=True),
            sa.Column("source_type", sa.String(length=32), nullable=False),
            sa.Column("source_id", sa.String(length=64), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["caisse_id"], ["caisses.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("code", name="uq_alertes_code"),
        )
        op.create_index(op.f("ix_alertes_code"), "alertes", ["code"], unique=False)
        op.create_index(op.f("ix_alertes_rule_code"), "alertes", ["rule_code"], unique=False)

    if "versements" not in tables:
        op.create_table(
            "versements",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("versement_id", sa.String(length=32), nullable=False),
            sa.Column("date_versement", sa.Date(), nullable=False),
            sa.Column("scope", sa.String(length=16), nullable=False),
            sa.Column("montant_theorique_fcfa", sa.Integer(), nullable=False),
            sa.Column("montant_verse_fcfa", sa.Integer(), nullable=False),
            sa.Column("ecart_fcfa", sa.Integer(), nullable=False),
            sa.Column("note", sa.String(length=255), nullable=True),
            sa.Column("justificatif_filename", sa.String(length=255), nullable=False),
            sa.Column("justificatif_content_type", sa.String(length=120), nullable=False),
            sa.Column("justificatif_bytes", sa.LargeBinary(), nullable=False),
            sa.Column("declared_by_id", sa.Integer(), nullable=False),
            sa.Column("statut", sa.String(length=16), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["declared_by_id"], ["users.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("versement_id", name="uq_versements_versement_id"),
        )
        op.create_index(op.f("ix_versements_versement_id"), "versements", ["versement_id"], unique=False)
        op.create_index(op.f("ix_versements_date_versement"), "versements", ["date_versement"], unique=False)
        op.create_index(op.f("ix_versements_scope"), "versements", ["scope"], unique=False)

    if "versement_caisses" not in tables:
        op.create_table(
            "versement_caisses",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("versement_id_fk", sa.Integer(), nullable=False),
            sa.Column("caisse_id", sa.Integer(), nullable=False),
            sa.Column("montant_theorique_fcfa", sa.Integer(), nullable=False),
            sa.ForeignKeyConstraint(["caisse_id"], ["caisses.id"], ondelete="RESTRICT"),
            sa.ForeignKeyConstraint(["versement_id_fk"], ["versements.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "versement_caisses" in tables:
        op.drop_table("versement_caisses")

    if "versements" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("versements")}
        for index_name in [op.f("ix_versements_scope"), op.f("ix_versements_date_versement"), op.f("ix_versements_versement_id")]:
            if index_name in indexes:
                op.drop_index(index_name, table_name="versements")
        op.drop_table("versements")

    if "alertes" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("alertes")}
        for index_name in [op.f("ix_alertes_rule_code"), op.f("ix_alertes_code")]:
            if index_name in indexes:
                op.drop_index(index_name, table_name="alertes")
        op.drop_table("alertes")

    if "factures" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("factures")}
        for index_name in [
            op.f("ix_factures_statut_document"),
            op.f("ix_factures_moyen_paiement_snapshot"),
            op.f("ix_factures_id_visite_snapshot"),
            op.f("ix_factures_numero_facture"),
        ]:
            if index_name in indexes:
                op.drop_index(index_name, table_name="factures")
        op.drop_table("factures")
