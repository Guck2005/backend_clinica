from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Visit(Base):
    __tablename__ = "visits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_visite: Mapped[str | None] = mapped_column(String(20), unique=True, index=True, nullable=True)
    patient_nom: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    patient_prenom: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    patient_tel: Mapped[str] = mapped_column(String(32), nullable=False)
    patient_tel_normalized: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    motif_visite: Mapped[str] = mapped_column(String(255), nullable=False)
    service_oriente: Mapped[str] = mapped_column(String(120), index=True, nullable=False)
    agent_accueil_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), nullable=False)
    statut: Mapped[str] = mapped_column(String(32), index=True, default="EN_ATTENTE", nullable=False)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
