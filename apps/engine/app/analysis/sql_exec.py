"""Execute guarded SQL through the least-privilege analytics role."""

from __future__ import annotations

import datetime as dt
import decimal
import time
import uuid
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from psycopg import errors as pgerr
from sqlalchemy import Engine, create_engine

from app.analysis.sql_guard import MAX_ROWS
from app.config import get_settings
from app.data.storage import raw_connection

STATEMENT_TIMEOUT_MS = 10_000


class SqlExecutionError(RuntimeError):
    """A failure the model can act on (bad column, type mismatch, timeout). Message is safe to show."""


@dataclass
class SqlResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int  # rows returned (capped)
    truncated: bool
    duration_ms: float


@lru_cache
def analytics_engine() -> Engine:
    url = get_settings().analytics_database_url.get_secret_value()
    if not url:
        raise SqlExecutionError("The analytics database role is not configured.")
    sa_url = url.replace("postgresql://", "postgresql+psycopg://", 1) if url.startswith("postgresql://") else url
    return create_engine(
        sa_url, pool_size=3, max_overflow=2, pool_pre_ping=True, pool_recycle=300,
        connect_args={"prepare_threshold": None, "connect_timeout": 15},
    )


def to_jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (bool, int, str)):
        return v
    if isinstance(v, float):
        return v if v == v and v not in (float("inf"), float("-inf")) else None
    if isinstance(v, decimal.Decimal):
        f = float(v)
        return int(f) if f.is_integer() and abs(f) < 1e15 and v == v.to_integral_value() else f
    if isinstance(v, (dt.datetime, dt.date, dt.time)):
        return v.isoformat()
    if isinstance(v, dt.timedelta):
        return v.total_seconds()
    if isinstance(v, uuid.UUID):
        return str(v)
    if isinstance(v, (list, tuple)):
        return [to_jsonable(x) for x in v]
    return str(v)


def _friendly(exc: Exception) -> str:
    if isinstance(exc, pgerr.QueryCanceled):
        return f"The query ran longer than {STATEMENT_TIMEOUT_MS // 1000} seconds and was stopped. Simplify it or aggregate earlier."
    primary = getattr(getattr(exc, "diag", None), "message_primary", None) or "The database rejected the query."
    return primary[:300]


def execute_trusted(query: Any, params: list[Any] | None = None) -> list[tuple]:
    """Run a query that this application built itself (identifiers quoted, values bound). Used for validation only."""
    try:
        with raw_connection(analytics_engine()) as raw:
            raw.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
            raw.execute("SET TRANSACTION READ ONLY")
            return raw.execute(query, params or []).fetchall()
    except pgerr.Error as exc:
        raise SqlExecutionError(_friendly(exc)) from exc


def execute_readonly(executed_sql: str) -> SqlResult:
    """Run an already-guarded statement. Never pass unvalidated text to this function."""
    started = time.perf_counter()
    try:
        with raw_connection(analytics_engine()) as raw:
            raw.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
            raw.execute("SET TRANSACTION READ ONLY")
            cur = raw.execute(executed_sql)
            columns = [c.name for c in cur.description or []]
            fetched = cur.fetchmany(MAX_ROWS + 1)
    except SqlExecutionError:
        raise
    except pgerr.Error as exc:
        raise SqlExecutionError(_friendly(exc)) from exc
    truncated = len(fetched) > MAX_ROWS
    rows = [[to_jsonable(v) for v in row] for row in fetched[:MAX_ROWS]]
    return SqlResult(columns, rows, len(rows), truncated, round((time.perf_counter() - started) * 1000, 1))
