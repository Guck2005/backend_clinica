from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Invoice(Base):
    __tablename__ = "factures"
    __table_args__ = (
        UniqueConstraint("numero_facture", name="uq_factures_numero_facture"),
        UniqueConstraint("transaction_id", name="uq_factures_transaction_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    numero_facture: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False)
    id_visite_snapshot: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    patient_nom_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    patient_tel_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    moyen_paiement_snapshot: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    reference_snapshot: Mapped[str | None] = mapped_column(String(120), nullable=True)
    statut_document: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    mention_paiement: Mapped[str | None] = mapped_column(String(255), nullable=True)
    public_token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    sms_status: Mapped[str] = mapped_column(String(32), nullable=False, default="A_ENVOYER")
    sms_provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    sms_message_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    sms_error: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sms_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    transaction = relationship("Transaction", back_populates="invoice")
