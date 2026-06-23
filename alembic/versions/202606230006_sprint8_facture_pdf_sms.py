"""sprint 8 facture pdf sms

Revision ID: 202606230006
Revises: 202606230005
Create Date: 2026-06-23
"""

from __future__ import annotations

from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


revision: str = "202606230006"
down_revision: Union[str, None] = "202606230005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "factures" not in tables:
        return

    columns = {column["name"] for column in inspector.get_columns("factures")}
    indexes = {index["name"] for index in inspector.get_indexes("factures")}

    with op.batch_alter_table("factures") as batch_op:
        if "public_token" not in columns:
            batch_op.add_column(sa.Column("public_token", sa.String(length=64), nullable=True))
        if "sms_status" not in columns:
            batch_op.add_column(sa.Column("sms_status", sa.String(length=32), nullable=False, server_default="A_ENVOYER"))
        if "sms_provider" not in columns:
            batch_op.add_column(sa.Column("sms_provider", sa.String(length=32), nullable=True))
        if "sms_message_id" not in columns:
            batch_op.add_column(sa.Column("sms_message_id", sa.String(length=120), nullable=True))
        if "sms_error" not in columns:
            batch_op.add_column(sa.Column("sms_error", sa.String(length=255), nullable=True))
        if "sms_sent_at" not in columns:
            batch_op.add_column(sa.Column("sms_sent_at", sa.DateTime(timezone=True), nullable=True))

    factures = sa.table(
        "factures",
        sa.column("id", sa.Integer()),
        sa.column("public_token", sa.String(length=64)),
        sa.column("sms_status", sa.String(length=32)),
    )

    rows = bind.execute(sa.select(factures.c.id, factures.c.public_token, factures.c.sms_status)).all()
    for row in rows:
        current_token = row.public_token
        current_status = row.sms_status
        update_values: dict[str, object] = {}
        if not current_token:
            update_values["public_token"] = uuid4().hex
        if not current_status:
            update_values["sms_status"] = "A_ENVOYER"
        if update_values:
            bind.execute(
                sa.update(factures)
                .where(factures.c.id == row.id)
                .values(**update_values)
            )

    if "ix_factures_public_token" not in indexes:
        op.create_index("ix_factures_public_token", "factures", ["public_token"], unique=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "factures" not in tables:
        return

    indexes = {index["name"] for index in inspector.get_indexes("factures")}
    if "ix_factures_public_token" in indexes:
        op.drop_index("ix_factures_public_token", table_name="factures")

    columns = {column["name"] for column in inspector.get_columns("factures")}
    with op.batch_alter_table("factures") as batch_op:
        if "sms_sent_at" in columns:
            batch_op.drop_column("sms_sent_at")
        if "sms_error" in columns:
            batch_op.drop_column("sms_error")
        if "sms_message_id" in columns:
            batch_op.drop_column("sms_message_id")
        if "sms_provider" in columns:
            batch_op.drop_column("sms_provider")
        if "sms_status" in columns:
            batch_op.drop_column("sms_status")
        if "public_token" in columns:
            batch_op.drop_column("public_token")
