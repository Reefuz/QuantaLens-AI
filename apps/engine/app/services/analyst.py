"""Run an analysis and persist everything it did.

The agent runs in a background thread that owns its own database session. The HTTP response streams events from a
queue, so closing the browser does not interrupt the run: the answer, the SQL and Python logs and the charts are
saved either way and are there when the user comes back.
"""

from __future__ import annotations

import logging
import queue
import threading
import uuid
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis.agent import run_agent
from app.analysis.dataset_access import resolve_dataset
from app.analysis.llm import LLMClient
from app.db import get_sessionmaker
from app.models import AnalysisPlan, AnalysisSession, ChartRecord, Conversation, Dataset, Message, PythonExecutionLog, SqlExecutionLog
from app.models.base import utcnow

logger = logging.getLogger("quantalens.analyst")
MAX_QUESTION_CHARS = 2000
DEFAULT_TITLE = "New analysis"

# Seams for tests.
SESSION_FACTORY: Callable[[], Session] = lambda: get_sessionmaker()()  # noqa: E731
LLM_FACTORY: Callable[[], Any] = LLMClient

_active: set[uuid.UUID] = set()
_active_lock = threading.Lock()
_DONE = object()


def try_acquire(conversation_id: uuid.UUID) -> bool:
    with _active_lock:
        if conversation_id in _active:
            return False
        _active.add(conversation_id)
        return True


def release(conversation_id: uuid.UUID) -> None:
    with _active_lock:
        _active.discard(conversation_id)


def title_from(question: str) -> str:
    t = " ".join(question.split())
    return (t[:57] + "...") if len(t) > 60 else t


def message_dict(m: Message) -> dict[str, Any]:
    return {"id": str(m.id), "role": m.role, "content": m.content, "payload": m.payload, "created_at": m.created_at.isoformat()}


def _summary_text(payload: dict[str, Any]) -> str:
    if payload["type"] == "answer":
        return payload["answer"]["executive_summary"]
    if payload["type"] == "clarification":
        return payload["question"]
    return payload.get("error") or "The analysis could not be completed."


def _persist(db: Session, conversation: Conversation, session: AnalysisSession, payload: dict[str, Any]) -> Message:
    for run in payload["sql"]:
        db.add(SqlExecutionLog(
            session_id=session.id, sql_text=run["sql"], executed_sql=run.get("executed_sql"), explanation=run.get("purpose"),
            tables=run.get("tables") or [], columns=run.get("columns") or [], status=run["status"], duration_ms=run.get("duration_ms"),
            row_count=run.get("row_count"), error=(run.get("error") or "")[:500] or None,
        ))
    for run in payload["python"]:
        db.add(PythonExecutionLog(
            session_id=session.id, code=run["code"], status=run["status"], duration_ms=run.get("duration_ms"),
            stdout=run.get("stdout") or None, error=run.get("error"), packages=run.get("packages") or [],
        ))
    for chart in payload["charts"]:
        db.add(ChartRecord(session_id=session.id, spec=chart))
    if payload.get("plan"):
        db.add(AnalysisPlan(session_id=session.id, steps=payload["plan"]["steps"], assumptions=payload["plan"]["assumptions"]))
    msg = Message(conversation_id=conversation.id, role="assistant", content=_summary_text(payload)[:20000], payload={**payload, "session_id": str(session.id)})
    db.add(msg)
    db.flush()
    session.message_id = msg.id
    session.status = {"answer": "completed", "clarification": "clarification", "error": "failed"}.get(payload["type"], "failed")
    session.events = payload["timeline"]
    session.model = payload.get("model")
    session.finished_at = utcnow()
    conversation.updated_at = utcnow()
    db.commit()
    return msg


def run_and_persist(conversation_id: uuid.UUID, question: str, emit: Callable[[dict[str, Any]], None]) -> None:
    """Executed in a worker thread. Always emits a terminal event, then releases the conversation."""
    try:
        with SESSION_FACTORY() as db:
            conversation = db.get(Conversation, conversation_id)
            dataset = db.get(Dataset, conversation.dataset_id) if conversation else None
            if conversation is None or dataset is None:
                emit({"type": "error", "message": "This conversation or its dataset no longer exists."})
                return
            prior = list(db.scalars(select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)))
            history = [{"role": m.role, "content": m.content, "payload": m.payload} for m in prior]
            user_msg = Message(conversation_id=conversation.id, role="user", content=question)
            db.add(user_msg)
            if conversation.title == DEFAULT_TITLE and not prior:
                conversation.title = title_from(question)
            conversation.updated_at = utcnow()
            session = AnalysisSession(conversation_id=conversation.id, question=question, status="running", events=[])
            db.add(session)
            db.commit()
            emit({"type": "start", "session_id": str(session.id), "user_message": message_dict(user_msg), "title": conversation.title})
            try:
                handle = resolve_dataset(db, dataset)
            except ValueError as exc:
                payload = {"type": "error", "error": str(exc), "answer": None, "plan": None, "results": [], "charts": [], "sql": [], "python": [],
                           "validation": {"status": "not_validated", "checks": [], "warnings": []}, "dataset": None, "timeline": [], "model": None, "duration_ms": 0}
            else:
                payload = run_agent(handle=handle, question=question, history=history, llm=LLM_FACTORY(), emit=emit)
            msg = _persist(db, conversation, session, payload)
            emit({"type": "final", "message": message_dict(msg), "title": conversation.title})
    except Exception as exc:  # noqa: BLE001 - type only
        logger.error("Analysis run failed: %s", type(exc).__name__)
        emit({"type": "error", "message": "The analysis could not be saved. Please try again."})
    finally:
        release(conversation_id)
        emit({"type": "end"})


def start_stream(conversation_id: uuid.UUID, question: str):
    """Start the worker and return a sync generator of NDJSON-ready dicts. The caller must have acquired the conversation."""
    q: queue.Queue = queue.Queue()
    threading.Thread(target=run_and_persist, args=(conversation_id, question, q.put), daemon=True, name="analyst-run").start()

    def events():
        while True:
            try:
                item = q.get(timeout=15)
            except queue.Empty:
                yield {"type": "ping"}
                continue
            yield item
            if item.get("type") == "end":
                return

    return events()
