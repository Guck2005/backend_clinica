from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Caisse(Base):
    __tablename__ = "caisses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nom: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    actif: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
