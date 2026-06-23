from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Alert(Base):
    __tablename__ = "alertes"
    __table_args__ = (UniqueConstraint("code", name="uq_alertes_code"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    rule_code: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    rule_name: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    gravite: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE")
    caisse_id: Mapped[int | None] = mapped_column(ForeignKey("caisses.id", ondelete="SET NULL"), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    details_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    impact_amount_fcfa: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notification_email_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    notification_email_sent_at = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_at = mapped_column(DateTime(timezone=True), nullable=True)
    first_detected_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_detected_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    caisse = relationship("Caisse")
