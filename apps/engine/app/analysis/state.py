"""Per-run state shared by every tool. Charts, validation and the final answer are all built from
`results`, so what the user sees cannot drift from what was computed."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from app.analysis.dataset_access import DatasetHandle

PREVIEW_ROWS = 25


@dataclass
class StoredResult:
    id: str
    source: str  # "sql" | "python"
    step: int
    label: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool = False

    def column_index(self, name: str) -> int:
        try:
            return self.columns.index(name)
        except ValueError:
            raise KeyError(name) from None

    def column(self, name: str) -> list[Any]:
        i = self.column_index(name)
        return [r[i] for r in self.rows]

    def preview(self, n: int = PREVIEW_ROWS) -> dict[str, Any]:
        return {"result_id": self.id, "columns": self.columns, "rows": self.rows[:n], "row_count": self.row_count,
                "truncated": self.truncated, "showing": min(n, len(self.rows))}

    def to_record(self) -> dict[str, Any]:
        return {"id": self.id, "source": self.source, "step": self.step, "label": self.label, "columns": self.columns,
                "rows": self.rows, "row_count": self.row_count, "truncated": self.truncated}


@dataclass
class RunState:
    handle: DatasetHandle
    emit: Callable[[dict[str, Any]], None]
    started: float = field(default_factory=time.perf_counter)
    results: dict[str, StoredResult] = field(default_factory=dict)
    sql_runs: list[dict[str, Any]] = field(default_factory=list)
    python_runs: list[dict[str, Any]] = field(default_factory=list)
    charts: list[dict[str, Any]] = field(default_factory=list)
    validations: list[dict[str, Any]] = field(default_factory=list)
    plan: dict[str, Any] | None = None
    inspected: bool = False
    validation_called: bool = False
    steps: int = 0
    _frame: Any = None

    def next_result_id(self) -> str:
        return f"r{len(self.results) + 1}"

    def add_result(self, **kw: Any) -> StoredResult:
        r = StoredResult(id=self.next_result_id(), step=self.steps, **kw)
        self.results[r.id] = r
        return r

    def get_result(self, result_id: str) -> StoredResult:
        r = self.results.get(result_id)
        if r is None:
            known = ", ".join(self.results) or "none yet"
            raise KeyError(f"There is no result '{result_id}'. Available results: {known}.")
        return r

    def frame(self):
        from app.analysis.dataset_access import load_dataframe

        if self._frame is None:
            self._frame = load_dataframe(self.handle)
        return self._frame
