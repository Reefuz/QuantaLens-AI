"""The agent loop: question in, structured and verifiable analysis out.

The model decides which tools to call and in what order. This module enforces the guard rails around that:
a step and time budget, validation before answering, structured final output, and honest timeline events that
correspond to work that actually ran. The model's private reasoning is never captured or exposed.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from app.analysis import grounding, validation
from app.analysis.dataset_access import DatasetHandle
from app.analysis.llm import LLMError, parse_tool_calls
from app.analysis.prompts import SYSTEM_PROMPT, build_history
from app.analysis.state import RunState
from app.analysis.tools import TERMINAL_TOOLS, TOOLS, dispatch

logger = logging.getLogger("quantalens.agent")
MAX_ROUNDS = 14
TIME_BUDGET_S = 170
PAYLOAD_ROWS = 300

TITLES = {
    "understand": "Understanding your question",
    "inspect_dataset": "Inspecting dataset",
    "plan_analysis": "Planning analysis",
    "execute_sql": "Running SQL query",
    "execute_python": "Running Python analysis",
    "generate_chart": "Generating visualisation",
    "validate_results": "Validating results",
    "explain_results": "Preparing insights",
    "request_clarification": "Asking for clarification",
}


# ── structured final answer ────────────────────────────────────────────────

def _strs(limit: int, each: int):
    def clip(v: Any) -> list[str]:
        return [str(x).strip()[:each] for x in (v or []) if str(x).strip()][:limit]
    return field_validator("*", mode="before")(clip)


class Finding(BaseModel):
    finding: str = Field(max_length=700)
    evidence: str = Field(default="", max_length=900)
    kind: Literal["observed", "statistical", "possible_explanation"] = "observed"

    @field_validator("kind", mode="before")
    @classmethod
    def _kind(cls, v: Any) -> str:
        return v if v in ("observed", "statistical", "possible_explanation") else "observed"


class Answer(BaseModel):
    executive_summary: str = Field(min_length=1, max_length=2000)
    key_findings: list[Finding] = Field(min_length=1, max_length=8)
    business_implications: list[str] = []
    recommendations: list[str] = []
    limitations: list[str] = []
    assumptions: list[str] = []
    chart_ids: list[str] = []
    follow_up_questions: list[str] = []

    @field_validator("business_implications", "recommendations", "limitations", "assumptions", "follow_up_questions", mode="before")
    @classmethod
    def _clip(cls, v: Any) -> list[str]:
        return [str(x).strip()[:700] for x in (v or []) if str(x).strip()][:8]


# ── helpers ────────────────────────────────────────────────────────────────

def _summarise(name: str, out: dict[str, Any], state: RunState) -> tuple[str, str, dict[str, Any] | None]:
    """(status, detail, ref) for the timeline, derived from the tool's real output."""
    if "error" in out:
        ref = {"type": "sql", "index": len(state.sql_runs)} if name == "execute_sql" else {"type": "python", "index": len(state.python_runs)} if name == "execute_python" else None
        return "error", str(out["error"])[:240], ref
    if name == "inspect_dataset":
        return "done", f"{len(out['columns'])} columns, {out['rows']:,} rows ({out['version']} data)", None
    if name == "plan_analysis":
        return "done", f"{out.get('recorded_steps', 0)} steps", None
    if name == "execute_sql":
        run = state.sql_runs[-1]
        return "done", f"{run['row_count']:,} rows in {run['duration_ms']:.0f} ms" + (" (truncated)" if run.get("truncated") else ""), {"type": "sql", "index": run["index"]}
    if name == "execute_python":
        run = state.python_runs[-1]
        return "done", f"Finished in {run['duration_ms']:.0f} ms", {"type": "python", "index": run["index"]}
    if name == "generate_chart":
        return "done", f"{out['type']} chart, {out['points']} data points", {"type": "chart", "id": out["chart_id"]}
    if name == "validate_results":
        counts = {s: sum(1 for c in out["checks"] if c["status"] == s) for s in ("verified", "failed", "unverified", "warning")}
        return ("error" if counts["failed"] else "done"), ", ".join(f"{n} {s}" for s, n in counts.items() if n), {"type": "validation"}
    return "done", "", None


def _payload_results(state: RunState) -> list[dict[str, Any]]:
    out = []
    for r in state.results.values():
        rec = r.to_record()
        rec["rows"] = rec["rows"][:PAYLOAD_ROWS]
        rec["rows_in_payload"] = len(rec["rows"])
        out.append(rec)
    return out


def _validation_block(state: RunState) -> dict[str, Any]:
    return {
        "status": validation.overall_status(state.validations),
        "checks": state.validations,
        "warnings": validation.automatic_warnings(state),
    }


def _assemble(state: RunState, kind: str, timeline: list[dict], model: str | None, started: float, **extra: Any) -> dict[str, Any]:
    h = state.handle
    return {
        "type": kind, "plan": state.plan, "results": _payload_results(state), "charts": state.charts,
        "sql": state.sql_runs, "python": state.python_runs, "validation": _validation_block(state),
        "dataset": {"id": h.dataset_id, "name": h.name, "version": h.version, "rows": h.row_count},
        "timeline": timeline, "model": model, "duration_ms": round((time.perf_counter() - started) * 1000), **extra,
    }


def _clean_assistant_message(msg: dict[str, Any]) -> dict[str, Any]:
    out = {"role": "assistant", "content": msg.get("content")}
    if msg.get("tool_calls"):
        out["tool_calls"] = msg["tool_calls"]  # sent back unchanged, including provider thought signatures
    return out


# ── the loop ───────────────────────────────────────────────────────────────

def run_agent(*, handle: DatasetHandle, question: str, history: list[dict], llm: Any, emit: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    started = time.perf_counter()
    state = RunState(handle=handle, emit=emit)
    timeline: list[dict[str, Any]] = []
    model_used: str | None = None

    def begin(key: str, detail: str = "") -> dict[str, Any]:
        step = {"id": len(timeline) + 1, "key": key, "title": TITLES.get(key, key), "status": "running", "detail": detail, "ms": None, "ref": None, "_t": time.perf_counter()}
        timeline.append(step)
        emit({"type": "step", **{k: v for k, v in step.items() if k != "_t"}})
        return step

    def finish(step: dict[str, Any], status: str, detail: str = "", ref: dict | None = None) -> None:
        step.update(status=status, detail=detail or step["detail"], ms=round((time.perf_counter() - step.pop("_t", started)) * 1000), ref=ref)
        emit({"type": "step", **step})

    notify = lambda m: emit({"type": "notice", "message": m})  # noqa: E731
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}, *build_history(history), {"role": "user", "content": question}]
    nudged_text = nudged_validate = 0
    answer: Answer | None = None
    clarification: dict[str, Any] | None = None
    fallback_text: str | None = None
    understand = begin("understand")

    try:
        for rnd in range(MAX_ROUNDS):
            if time.perf_counter() - started > TIME_BUDGET_S:
                break
            msg, model_used = llm.chat(messages, TOOLS, notify=notify)
            if understand is not None:
                finish(understand, "done")
                understand = None
            messages.append(_clean_assistant_message(msg))
            calls = parse_tool_calls(msg)
            if not calls:
                text = (msg.get("content") or "").strip()
                if nudged_text == 0:
                    nudged_text = 1
                    messages.append({"role": "user", "content": "Continue by calling a tool. Deliver your answer with explain_results, or call request_clarification."})
                    continue
                fallback_text = text
                break
            done = False
            for call in calls:
                name = call["name"]
                state.steps += 1
                if call["parse_error"]:
                    messages.append({"role": "tool", "tool_call_id": call["id"], "name": name, "content": json.dumps({"error": call["parse_error"]})})
                    continue
                if name == "explain_results":
                    if state.results and not state.validation_called and nudged_validate == 0:
                        nudged_validate = 1
                        messages.append({"role": "tool", "tool_call_id": call["id"], "name": name, "content": json.dumps({"error": "Not accepted yet. Call validate_results for your headline figures first, then call explain_results again."})})
                        continue
                    step = begin("explain_results")
                    try:
                        answer = Answer.model_validate(call["arguments"])
                    except ValidationError as exc:
                        finish(step, "error", "The answer was incomplete.")
                        problems = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:4])
                        messages.append({"role": "tool", "tool_call_id": call["id"], "name": name, "content": json.dumps({"error": f"Invalid answer ({problems}). Provide executive_summary, at least one key finding and limitations."})})
                        continue
                    finish(step, "done", f"{len(answer.key_findings)} findings")
                    done = True
                    break
                if name == "request_clarification":
                    q = str(call["arguments"].get("question") or "").strip()
                    if not q:
                        messages.append({"role": "tool", "tool_call_id": call["id"], "name": name, "content": json.dumps({"error": "The question is empty."})})
                        continue
                    clarification = {"question": q[:600], "options": [str(o)[:160] for o in (call["arguments"].get("options") or [])][:5]}
                    finish(begin("request_clarification"), "done", "Waiting for your answer")
                    done = True
                    break
                step = begin(name, str(call["arguments"].get("purpose") or "")[:200])
                raw = dispatch(state, name, call["arguments"])
                try:
                    out = json.loads(raw)
                except ValueError:
                    out = {"error": "Tool output was unreadable."}
                status, detail, ref = _summarise(name, out, state)
                finish(step, status, detail, ref)
                messages.append({"role": "tool", "tool_call_id": call["id"], "name": name, "content": raw})
            if done:
                break

        if answer is None and clarification is None and fallback_text is None:
            # Out of rounds or time: force a final answer from what has been computed so far.
            step = begin("explain_results", "Out of steps. Summarising what was found.")
            forced = [t for t in TOOLS if t["function"]["name"] == "explain_results"]
            messages.append({"role": "user", "content": "You are out of steps. Call explain_results now using only the results you already have, and state in limitations that the analysis was cut short."})
            msg, model_used = llm.chat(messages, forced, tool_choice={"type": "function", "function": {"name": "explain_results"}}, notify=notify)
            calls = parse_tool_calls(msg)
            try:
                answer = Answer.model_validate(calls[0]["arguments"]) if calls else None
            except (ValidationError, IndexError):
                answer = None
            finish(step, "done" if answer else "error", "" if answer else "No final answer was produced.")
    except LLMError as exc:
        if understand is not None:
            finish(understand, "error", str(exc))
        emit({"type": "error", "message": str(exc)})
        return _assemble(state, "error", timeline, model_used, started, error=str(exc), answer=None)
    except Exception as exc:  # noqa: BLE001 - never leak internals; type only
        logger.error("Agent run failed: %s", type(exc).__name__)
        emit({"type": "error", "message": "The analysis hit an unexpected problem."})
        return _assemble(state, "error", timeline, model_used, started, error="The analysis hit an unexpected problem. Please try again.", answer=None)

    for s in timeline:
        s.pop("_t", None)
    if clarification:
        return _assemble(state, "clarification", timeline, model_used, started, answer=None, **clarification)
    if answer is None:
        text = fallback_text or ""
        if not text:
            return _assemble(state, "error", timeline, model_used, started, error="The analyst could not produce an answer. Please rephrase the question.", answer=None)
        answer = Answer(executive_summary=text[:2000], key_findings=[Finding(finding=text[:700], evidence="", kind="observed")],
                        limitations=["The AI did not return a structured answer, so this text is shown as written and has not been checked."])
    known = {c["id"] for c in state.charts}
    answer.chart_ids = [c for c in answer.chart_ids if c in known] or [c["id"] for c in state.charts]
    dumped = answer.model_dump()
    payload = _assemble(state, "answer", timeline, model_used, started, answer=dumped)
    warn = grounding.grounding_warning(dumped, state)
    if warn:
        payload["validation"]["warnings"].append(warn)
    return payload
