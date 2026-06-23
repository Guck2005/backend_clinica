from datetime import date

from sqlalchemy import Date, DateTime, ForeignKey, Integer, LargeBinary, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Versement(Base):
    __tablename__ = "versements"
    __table_args__ = (UniqueConstraint("versement_id", name="uq_versements_versement_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    versement_id: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    date_versement: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    scope: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    montant_theorique_fcfa: Mapped[int] = mapped_column(Integer, nullable=False)
    montant_theorique_especes_fcfa: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    montant_theorique_cheques_fcfa: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    montant_compte_especes_fcfa: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    montant_remis_cheques_fcfa: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    montant_verse_fcfa: Mapped[int] = mapped_column(Integer, nullable=False)
    ecart_fcfa: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    justificatif_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    justificatif_content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    justificatif_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    declared_by_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    statut: Mapped[str] = mapped_column(String(16), nullable=False, default="EFFECTUE")
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    declared_by = relationship("User")
    caisses = relationship(
        "VersementCaisse",
        back_populates="versement",
        cascade="all, delete-orphan",
        order_by="VersementCaisse.id.asc()",
    )


class VersementCaisse(Base):
    __tablename__ = "versement_caisses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    versement_id_fk: Mapped[int] = mapped_column(ForeignKey("versements.id", ondelete="CASCADE"), nullable=False)
    caisse_id: Mapped[int] = mapped_column(ForeignKey("caisses.id", ondelete="RESTRICT"), nullable=False)
    montant_theorique_fcfa: Mapped[int] = mapped_column(Integer, nullable=False)

    versement = relationship("Versement", back_populates="caisses")
    caisse = relationship("Caisse")
