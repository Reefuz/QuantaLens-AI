import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin, JsonType


class Conversation(Base, IdMixin, CreatedMixin):
    __tablename__ = "conversations"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("datasets.id", ondelete="CASCADE"), index=True, nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), default="New analysis", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class Message(Base, IdMixin, CreatedMixin):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    role: Mapped[str] = mapped_column(String(12), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Structured assistant payload: findings, validation, chart refs. Never chain-of-thought.
    payload: Mapped[dict | None] = mapped_column(JsonType)


class AnalysisSession(Base, IdMixin, CreatedMixin):
    """One agent run answering one user message."""

    __tablename__ = "analysis_sessions"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversations.id", ondelete="CASCADE"), index=True, nullable=False
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("messages.id", ondelete="SET NULL"))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    events: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    model: Mapped[str | None] = mapped_column(String(80))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalysisPlan(Base, IdMixin, CreatedMixin):
    __tablename__ = "analysis_plans"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("analysis_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    steps: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    assumptions: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)


class SqlExecutionLog(Base, IdMixin, CreatedMixin):
    __tablename__ = "sql_execution_logs"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("analysis_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    sql_text: Mapped[str] = mapped_column(Text, nullable=False)  # as written by the model
    executed_sql: Mapped[str | None] = mapped_column(Text)  # the exact validated statement sent to the database
    explanation: Mapped[str | None] = mapped_column(Text)
    tables: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    columns: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    row_count: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(String(500))


class PythonExecutionLog(Base, IdMixin, CreatedMixin):
    __tablename__ = "python_execution_logs"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("analysis_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)  # exact code executed
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    stdout: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    packages: Mapped[list] = mapped_column(JsonType, default=list, nullable=False)


class ChartRecord(Base, IdMixin, CreatedMixin):
    __tablename__ = "generated_charts"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("analysis_sessions.id", ondelete="CASCADE"), index=True, nullable=False
    )
    spec: Mapped[dict] = mapped_column(JsonType, nullable=False)
