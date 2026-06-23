"""modules 10 11 13 14

Revision ID: 202606230007
Revises: 202606230006
Create Date: 2026-06-23
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "202606230007"
down_revision: Union[str, None] = "202606230006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "alertes" in tables:
        columns = {column["name"] for column in inspector.get_columns("alertes")}
        with op.batch_alter_table("alertes") as batch_op:
            batch_op.alter_column("rule_code", existing_type=sa.String(length=16), type_=sa.String(length=64))
            if "rule_name" not in columns:
                batch_op.add_column(sa.Column("rule_name", sa.String(length=160), nullable=False, server_default=""))
            if "status" not in columns:
                batch_op.add_column(sa.Column("status", sa.String(length=16), nullable=False, server_default="ACTIVE"))
            if "details_json" not in columns:
                batch_op.add_column(sa.Column("details_json", sa.JSON(), nullable=True))
            if "impact_amount_fcfa" not in columns:
                batch_op.add_column(sa.Column("impact_amount_fcfa", sa.Integer(), nullable=True))
            if "notification_email_status" not in columns:
                batch_op.add_column(sa.Column("notification_email_status", sa.String(length=32), nullable=True))
            if "notification_email_sent_at" not in columns:
                batch_op.add_column(sa.Column("notification_email_sent_at", sa.DateTime(timezone=True), nullable=True))
            if "resolved_at" not in columns:
                batch_op.add_column(sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
            if "first_detected_at" not in columns:
                batch_op.add_column(sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=True))
            if "last_detected_at" not in columns:
                batch_op.add_column(sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=True))

        alertes = sa.table(
            "alertes",
            sa.column("id", sa.Integer()),
            sa.column("rule_code", sa.String(length=64)),
            sa.column("rule_name", sa.String(length=160)),
            sa.column("status", sa.String(length=16)),
            sa.column("active", sa.Boolean()),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
            sa.column("first_detected_at", sa.DateTime(timezone=True)),
            sa.column("last_detected_at", sa.DateTime(timezone=True)),
        )

        existing_alerts = bind.execute(
            sa.select(
                alertes.c.id,
                alertes.c.rule_code,
                alertes.c.rule_name,
                alertes.c.status,
                alertes.c.active,
                alertes.c.created_at,
                alertes.c.updated_at,
                alertes.c.first_detected_at,
                alertes.c.last_detected_at,
            )
        ).all()
        mapping = {
            "A5": ("CHEQUE_REJETE_APRES_FACTURE", "Cheque rejete apres emission de facture"),
            "A7": ("ECART_VERSEMENT_BANCAIRE", "Ecart de versement bancaire"),
        }
        for row in existing_alerts:
            rule_code, rule_name = mapping.get(row.rule_code, (row.rule_code, row.rule_name or row.rule_code))
            bind.execute(
                sa.update(alertes)
                .where(alertes.c.id == row.id)
                .values(
                    rule_code=rule_code,
                    rule_name=rule_name,
                    status=row.status or ("ACTIVE" if row.active else "RESOLUE"),
                    first_detected_at=row.first_detected_at or row.created_at,
                    last_detected_at=row.last_detected_at or row.updated_at or row.created_at,
                )
            )

    if "versements" in tables:
        columns = {column["name"] for column in inspector.get_columns("versements")}
        with op.batch_alter_table("versements") as batch_op:
            if "montant_theorique_especes_fcfa" not in columns:
                batch_op.add_column(sa.Column("montant_theorique_especes_fcfa", sa.Integer(), nullable=False, server_default="0"))
            if "montant_theorique_cheques_fcfa" not in columns:
                batch_op.add_column(sa.Column("montant_theorique_cheques_fcfa", sa.Integer(), nullable=False, server_default="0"))
            if "montant_compte_especes_fcfa" not in columns:
                batch_op.add_column(sa.Column("montant_compte_especes_fcfa", sa.Integer(), nullable=False, server_default="0"))
            if "montant_remis_cheques_fcfa" not in columns:
                batch_op.add_column(sa.Column("montant_remis_cheques_fcfa", sa.Integer(), nullable=False, server_default="0"))

        versements = sa.table(
            "versements",
            sa.column("id", sa.Integer()),
            sa.column("montant_theorique_fcfa", sa.Integer()),
            sa.column("montant_verse_fcfa", sa.Integer()),
            sa.column("montant_theorique_especes_fcfa", sa.Integer()),
            sa.column("montant_theorique_cheques_fcfa", sa.Integer()),
            sa.column("montant_compte_especes_fcfa", sa.Integer()),
            sa.column("montant_remis_cheques_fcfa", sa.Integer()),
        )
        existing_versements = bind.execute(
            sa.select(
                versements.c.id,
                versements.c.montant_theorique_fcfa,
                versements.c.montant_verse_fcfa,
            )
        ).all()
        for row in existing_versements:
            bind.execute(
                sa.update(versements)
                .where(versements.c.id == row.id)
                .values(
                    montant_theorique_especes_fcfa=row.montant_theorique_fcfa or 0,
                    montant_theorique_cheques_fcfa=0,
                    montant_compte_especes_fcfa=row.montant_verse_fcfa or 0,
                    montant_remis_cheques_fcfa=0,
                )
            )

    if "audit_logs" not in tables:
        op.create_table(
            "audit_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("action_code", sa.String(length=64), nullable=False),
            sa.Column("action_label", sa.String(length=160), nullable=False),
            sa.Column("actor_id", sa.Integer(), nullable=True),
            sa.Column("actor_nom_snapshot", sa.String(length=160), nullable=True),
            sa.Column("actor_role_snapshot", sa.String(length=32), nullable=True),
            sa.Column("entity_type", sa.String(length=32), nullable=False),
            sa.Column("entity_id", sa.String(length=64), nullable=False),
            sa.Column("caisse_id", sa.Integer(), nullable=True),
            sa.Column("detail_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["caisse_id"], ["caisses.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_audit_logs_action_code"), "audit_logs", ["action_code"], unique=False)
        op.create_index(op.f("ix_audit_logs_entity_type"), "audit_logs", ["entity_type"], unique=False)
        op.create_index(op.f("ix_audit_logs_entity_id"), "audit_logs", ["entity_id"], unique=False)

    if "sync_jobs" not in tables:
        op.create_table(
            "sync_jobs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("job_type", sa.String(length=64), nullable=False),
            sa.Column("entity_type", sa.String(length=32), nullable=False),
            sa.Column("entity_id", sa.String(length=64), nullable=False),
            sa.Column("payload_json", sa.JSON(), nullable=True),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.String(length=255), nullable=True),
            sa.Column("scheduled_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_sync_jobs_job_type"), "sync_jobs", ["job_type"], unique=False)
        op.create_index(op.f("ix_sync_jobs_entity_type"), "sync_jobs", ["entity_type"], unique=False)
        op.create_index(op.f("ix_sync_jobs_entity_id"), "sync_jobs", ["entity_id"], unique=False)
        op.create_index(op.f("ix_sync_jobs_status"), "sync_jobs", ["status"], unique=False)

    if "backup_settings" not in tables:
        op.create_table(
            "backup_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("frequency_minutes", sa.Integer(), nullable=False, server_default="1440"),
            sa.Column("target_directory", sa.String(length=255), nullable=False, server_default="./backups"),
            sa.Column("retention_count", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("updated_by_id", sa.Integer(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )

    if "backup_runs" not in tables:
        op.create_table(
            "backup_runs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(length=16), nullable=False),
            sa.Column("file_path", sa.String(length=255), nullable=True),
            sa.Column("file_size_bytes", sa.Integer(), nullable=True),
            sa.Column("error_message", sa.String(length=255), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_backup_runs_status"), "backup_runs", ["status"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "backup_runs" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("backup_runs")}
        if op.f("ix_backup_runs_status") in indexes:
            op.drop_index(op.f("ix_backup_runs_status"), table_name="backup_runs")
        op.drop_table("backup_runs")

    if "backup_settings" in tables:
        op.drop_table("backup_settings")

    if "sync_jobs" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("sync_jobs")}
        for index_name in [
            op.f("ix_sync_jobs_status"),
            op.f("ix_sync_jobs_entity_id"),
            op.f("ix_sync_jobs_entity_type"),
            op.f("ix_sync_jobs_job_type"),
        ]:
            if index_name in indexes:
                op.drop_index(index_name, table_name="sync_jobs")
        op.drop_table("sync_jobs")

    if "audit_logs" in tables:
        indexes = {index["name"] for index in inspector.get_indexes("audit_logs")}
        for index_name in [
            op.f("ix_audit_logs_entity_id"),
            op.f("ix_audit_logs_entity_type"),
            op.f("ix_audit_logs_action_code"),
        ]:
            if index_name in indexes:
                op.drop_index(index_name, table_name="audit_logs")
        op.drop_table("audit_logs")

    if "versements" in tables:
        columns = {column["name"] for column in inspector.get_columns("versements")}
        with op.batch_alter_table("versements") as batch_op:
            for column_name in [
                "montant_remis_cheques_fcfa",
                "montant_compte_especes_fcfa",
                "montant_theorique_cheques_fcfa",
                "montant_theorique_especes_fcfa",
            ]:
                if column_name in columns:
                    batch_op.drop_column(column_name)

    if "alertes" in tables:
        columns = {column["name"] for column in inspector.get_columns("alertes")}
        with op.batch_alter_table("alertes") as batch_op:
            batch_op.alter_column("rule_code", existing_type=sa.String(length=64), type_=sa.String(length=16))
            for column_name in [
                "last_detected_at",
                "first_detected_at",
                "resolved_at",
                "notification_email_sent_at",
                "notification_email_status",
                "impact_amount_fcfa",
                "details_json",
                "status",
                "rule_name",
            ]:
                if column_name in columns:
                    batch_op.drop_column(column_name)
