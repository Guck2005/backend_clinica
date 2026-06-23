from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class CatalogueItem(Base):
    __tablename__ = "catalogue_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_element: Mapped[str] = mapped_column(String(40), unique=True, index=True, nullable=False)
    code_labo: Mapped[str | None] = mapped_column(String(40), index=True, nullable=True)
    type: Mapped[str] = mapped_column(String(40), index=True, default="Analyse", nullable=False)
    nom: Mapped[str] = mapped_column(String(255), nullable=False)
    service: Mapped[str] = mapped_column(String(120), index=True, default="Laboratoire", nullable=False)
    montant_fcfa: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hopital_id: Mapped[str] = mapped_column(String(80), default="HSJ-229", nullable=False)
    actif: Mapped[bool] = mapped_column(Boolean, default=True, index=True, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    tariff_history = relationship(
        "CatalogueTariffHistory",
        back_populates="catalogue_item",
        cascade="all, delete-orphan",
    )


class CatalogueTariffHistory(Base):
    __tablename__ = "catalogue_tariff_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    catalogue_item_id: Mapped[int] = mapped_column(
        ForeignKey("catalogue_items.id", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    ancien_montant_fcfa: Mapped[int] = mapped_column(Integer, nullable=False)
    nouveau_montant_fcfa: Mapped[int] = mapped_column(Integer, nullable=False)
    auteur_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    catalogue_item = relationship("CatalogueItem", back_populates="tariff_history")
