from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (UniqueConstraint("visit_id", name="uq_transactions_visit_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    visit_id: Mapped[int] = mapped_column(ForeignKey("visits.id", ondelete="RESTRICT"), nullable=False)
    caisse_id: Mapped[int | None] = mapped_column(ForeignKey("caisses.id", ondelete="SET NULL"), nullable=True)
    caissier_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    statut: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    montant_total_fcfa: Mapped[int] = mapped_column(Integer, nullable=False)
    montant_encaisse_fcfa: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    visit = relationship("Visit")
    caisse = relationship("Caisse")
    caissier = relationship("User")
    lines = relationship(
        "TransactionLine",
        back_populates="transaction",
        cascade="all, delete-orphan",
        order_by="TransactionLine.id.asc()",
    )
    payments = relationship("Payment", back_populates="transaction", cascade="all, delete-orphan")
    invoice = relationship("Invoice", back_populates="transaction", uselist=False)

    @property
    def latest_payment(self) -> "Payment | None":
        if not self.payments:
            return None
        return max(self.payments, key=lambda payment: (payment.attempt_no, payment.id))


class TransactionLine(Base):
    __tablename__ = "transaction_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False)
    catalogue_item_id: Mapped[int] = mapped_column(ForeignKey("catalogue_items.id", ondelete="RESTRICT"), nullable=False)
    code_element_snapshot: Mapped[str] = mapped_column(String(40), nullable=False)
    nom_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    type_snapshot: Mapped[str] = mapped_column(String(40), nullable=False)
    service_snapshot: Mapped[str] = mapped_column(String(120), nullable=False)
    quantite: Mapped[int] = mapped_column(Integer, nullable=False)
    prix_unitaire_fcfa: Mapped[int] = mapped_column(Integer, nullable=False)
    montant_ligne_fcfa: Mapped[int] = mapped_column(Integer, nullable=False)
    payable: Mapped[bool] = mapped_column(Boolean, nullable=False)
    motif_non_honore: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    transaction = relationship("Transaction", back_populates="lines")
    catalogue_item = relationship("CatalogueItem")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    moyen_paiement: Mapped[str] = mapped_column(String(32), nullable=False)
    statut: Mapped[str] = mapped_column(String(32), nullable=False)
    montant_fcfa: Mapped[int] = mapped_column(Integer, nullable=False)
    provider: Mapped[str | None] = mapped_column(String(32), nullable=True)
    provider_attempt_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    provider_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    operator_code: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reference_paiement: Mapped[str | None] = mapped_column(String(120), nullable=True)
    telephone_paiement: Mapped[str | None] = mapped_column(String(32), nullable=True)
    cheque_numero: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cheque_banque: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cheque_titulaire: Mapped[str | None] = mapped_column(String(120), nullable=True)
    raw_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    confirmed_at = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at = mapped_column(DateTime(timezone=True), nullable=True)

    transaction = relationship("Transaction", back_populates="payments")
