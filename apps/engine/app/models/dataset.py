import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin, JsonType, utcnow


class Dataset(Base, IdMixin, CreatedMixin):
    __tablename__ = "datasets"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(20), default="csv", nullable=False)  # csv | postgres
    is_sample: Mapped[bool] = mapped_column(default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="processing", nullable=False)  # processing | ready | cleaning | failed
    status_changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    # Tables in schema "qdata". The original is immutable; cleaned is created only after user approval.
    original_table: Mapped[str | None] = mapped_column(String(80))
    cleaned_table: Mapped[str | None] = mapped_column(String(80))
    row_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(String(500))


class DatasetMetadata(Base, IdMixin, CreatedMixin):
    """Schema and profiling output for a dataset (one row per dataset)."""

    __tablename__ = "dataset_metadata"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("datasets.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    columns: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    quality_report: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)


class CleaningOperation(Base, IdMixin, CreatedMixin):
    """Ordered transformation history. Proposed, then approved or rejected, then applied."""

    __tablename__ = "cleaning_history"

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("datasets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    operation: Mapped[str] = mapped_column(String(60), nullable=False)
    column_name: Mapped[str | None] = mapped_column(String(200))
    parameters: Mapped[dict] = mapped_column(JsonType, default=dict, nullable=False)
    affected_rows: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="proposed", nullable=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
