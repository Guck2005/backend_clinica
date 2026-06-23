from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action_code: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    action_label: Mapped[str] = mapped_column(String(160), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_nom_snapshot: Mapped[str] = mapped_column(String(160), nullable=False)
    actor_role_snapshot: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    caisse_id: Mapped[int | None] = mapped_column(ForeignKey("caisses.id", ondelete="SET NULL"), nullable=True)
    detail_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    actor = relationship("User")
    caisse = relationship("Caisse")
