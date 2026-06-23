from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class BackupSetting(Base):
    __tablename__ = "backup_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    frequency_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=1440)
    target_directory: Mapped[str] = mapped_column(String(255), nullable=False, default="./backups")
    retention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updated_at = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    updated_by = relationship("User")


class BackupRun(Base):
    __tablename__ = "backup_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), index=True, nullable=False, default="PENDING")
    file_path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(255), nullable=True)
    started_at = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = mapped_column(DateTime(timezone=True), nullable=True)
