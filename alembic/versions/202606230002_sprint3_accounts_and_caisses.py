"""sprint 3 accounts and caisses

Revision ID: 202606230002
Revises: 202606230001
Create Date: 2026-06-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "202606230002"
down_revision: Union[str, None] = "202606230001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "caisses" not in tables:
        op.create_table(
            "caisses",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("nom", sa.String(length=120), nullable=False),
            sa.Column("actif", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_caisses_nom"), "caisses", ["nom"], unique=True)

    if "visits" not in tables:
        op.create_table(
            "visits",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("id_visite", sa.String(length=20), nullable=True),
            sa.Column("patient_nom", sa.String(length=120), nullable=False),
            sa.Column("patient_prenom", sa.String(length=120), nullable=False),
            sa.Column("patient_tel", sa.String(length=32), nullable=False),
            sa.Column("patient_tel_normalized", sa.String(length=32), nullable=False),
            sa.Column("motif_visite", sa.String(length=255), nullable=False),
            sa.Column("service_oriente", sa.String(length=120), nullable=False),
            sa.Column("agent_accueil_id", sa.Integer(), nullable=False),
            sa.Column("statut", sa.String(length=32), nullable=False, server_default="EN_ATTENTE"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["agent_accueil_id"], ["users.id"], ondelete="RESTRICT"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_visits_id_visite"), "visits", ["id_visite"], unique=True)
        op.create_index(op.f("ix_visits_patient_nom"), "visits", ["patient_nom"], unique=False)
        op.create_index(op.f("ix_visits_patient_prenom"), "visits", ["patient_prenom"], unique=False)
        op.create_index(
            op.f("ix_visits_patient_tel_normalized"),
            "visits",
            ["patient_tel_normalized"],
            unique=False,
        )
        op.create_index(op.f("ix_visits_service_oriente"), "visits", ["service_oriente"], unique=False)
        op.create_index(op.f("ix_visits_statut"), "visits", ["statut"], unique=False)

    if "users" in tables:
        columns = {column["name"] for column in inspector.get_columns("users")}
        if "caisse_id" not in columns:
            with op.batch_alter_table("users") as batch_op:
                batch_op.add_column(sa.Column("caisse_id", sa.Integer(), nullable=True))
                batch_op.create_index(op.f("ix_users_caisse_id"), ["caisse_id"], unique=False)
                batch_op.create_foreign_key(
                    "fk_users_caisse_id_caisses",
                    "caisses",
                    ["caisse_id"],
                    ["id"],
                    ondelete="SET NULL",
                )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "users" in tables:
        columns = {column["name"] for column in inspector.get_columns("users")}
        if "caisse_id" in columns:
            foreign_keys = {fk["name"] for fk in inspector.get_foreign_keys("users")}
            indexes = {index["name"] for index in inspector.get_indexes("users")}
            with op.batch_alter_table("users") as batch_op:
                if "fk_users_caisse_id_caisses" in foreign_keys:
                    batch_op.drop_constraint("fk_users_caisse_id_caisses", type_="foreignkey")
                if op.f("ix_users_caisse_id") in indexes:
                    batch_op.drop_index(op.f("ix_users_caisse_id"))
                batch_op.drop_column("caisse_id")

    if "visits" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("visits")}
        if op.f("ix_visits_statut") in indexes:
            op.drop_index(op.f("ix_visits_statut"), table_name="visits")
        if op.f("ix_visits_service_oriente") in indexes:
            op.drop_index(op.f("ix_visits_service_oriente"), table_name="visits")
        if op.f("ix_visits_patient_tel_normalized") in indexes:
            op.drop_index(op.f("ix_visits_patient_tel_normalized"), table_name="visits")
        if op.f("ix_visits_patient_prenom") in indexes:
            op.drop_index(op.f("ix_visits_patient_prenom"), table_name="visits")
        if op.f("ix_visits_patient_nom") in indexes:
            op.drop_index(op.f("ix_visits_patient_nom"), table_name="visits")
        if op.f("ix_visits_id_visite") in indexes:
            op.drop_index(op.f("ix_visits_id_visite"), table_name="visits")
        op.drop_table("visits")

    if "caisses" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("caisses")}
        if op.f("ix_caisses_nom") in indexes:
            op.drop_index(op.f("ix_caisses_nom"), table_name="caisses")
        op.drop_table("caisses")
