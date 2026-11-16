"""Host side of the restricted Python runner: validate, stage data, run in a child process, collect results."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from app.analysis.python_guard import ALLOWED_IMPORTS, PythonCheck, PythonRejected, validate_python

logger = logging.getLogger(__name__)
RUNNER = Path(__file__).with_name("sandbox_runner.py")
TIMEOUT_S = 25  # overridden from settings at run time; module values remain the defaults used by tests
MEMORY_MB = 1024
_slots: threading.BoundedSemaphore | None = None
_slots_lock = threading.Lock()


def _limits() -> tuple[int, int, threading.BoundedSemaphore]:
    """(timeout, memory, semaphore). Configured through settings; a test that patches the module constants still wins."""
    global _slots
    from app.config import get_settings

    s = get_settings()
    with _slots_lock:
        if _slots is None:
            _slots = threading.BoundedSemaphore(max(1, s.python_max_concurrent))
    timeout = TIMEOUT_S if TIMEOUT_S != 25 else s.python_timeout_s
    memory = MEMORY_MB if MEMORY_MB != 1024 else s.python_memory_mb
    return timeout, memory, _slots


def _remove_dir(path: Path) -> None:
    """Windows can hold handles briefly after a killed child, so retry."""
    for _ in range(10):
        shutil.rmtree(path, ignore_errors=True)
        if not path.exists():
            return
        time.sleep(0.2)


def _sweep_stale(max_age_s: int = 600) -> None:
    """Remove work directories left behind by a crashed process."""
    cutoff = time.time() - max_age_s
    for p in Path(tempfile.gettempdir()).glob("ql_py_*"):
        try:
            if p.stat().st_mtime < cutoff:
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


class PythonExecutionError(RuntimeError):
    """Execution failed in a way the model can act on. Message is safe to show."""


@dataclass
class PythonResult:
    ok: bool
    stdout: str
    duration_ms: float
    packages: list[str]
    limits_enforced: bool
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    versions: dict[str, str] = field(default_factory=dict)


def _child_env() -> dict[str, str]:
    """Nothing from the parent's environment is passed through, so no secrets are reachable."""
    env = {
        "PYTHONHASHSEED": "0", "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
        "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
    }
    if os.name == "nt":  # Windows needs these for the interpreter and DLL loading
        for key in ("SYSTEMROOT", "SYSTEMDRIVE", "PATH"):
            if key in os.environ:
                env[key] = os.environ[key]
    return env


def run_python(code: str, df: pd.DataFrame, extra_frames: dict[str, pd.DataFrame] | None = None, *, _validate: bool = True) -> PythonResult:
    """`_validate=False` exists only so tests can prove the runner's own defences hold when static checks are bypassed."""
    check: PythonCheck = validate_python(code) if _validate else PythonCheck(packages=[], uses_frames=[])
    frames = {"df": df, **(extra_frames or {})}
    timeout_s, memory_mb, slots = _limits()
    _sweep_stale()
    workdir = Path(tempfile.mkdtemp(prefix="ql_py_"))
    try:
        files = {}
        for name, frame in frames.items():
            fname = f"{name}.parquet"
            frame.to_parquet(workdir / fname, index=False)
            files[name] = fname
        (workdir / "code.py").write_text(code, encoding="utf-8")
        preload = [p for p in check.packages if p in ("sklearn", "scipy")]
        (workdir / "request.json").write_text(
            json.dumps({
                "frames": files, "timeout_s": timeout_s, "memory_mb": memory_mb, "preload": preload,
                "allowed_imports": {k: (sorted(v) if v else None) for k, v in ALLOWED_IMPORTS.items()},
            }),
            encoding="utf-8",
        )
        with slots:
            try:
                proc = subprocess.run(
                    [sys.executable, "-I", str(RUNNER), str(workdir)],
                    cwd=workdir, env=_child_env(), capture_output=True, timeout=timeout_s, stdin=subprocess.DEVNULL,
                )
            except subprocess.TimeoutExpired as exc:
                raise PythonExecutionError(f"The analysis ran longer than {timeout_s} seconds and was stopped.") from exc
        result_file = workdir / "result.json"
        if not result_file.exists():
            tail = proc.stderr.decode("utf-8", "replace")[-300:]
            logger.warning("python sandbox exited %s without a result: %s", proc.returncode, tail[-200:])
            if "MemoryError" in tail or proc.returncode in (-9, 137):
                raise PythonExecutionError("The analysis ran out of memory and was stopped.")
            raise PythonExecutionError("The analysis process stopped unexpectedly.")
        payload = json.loads(result_file.read_text(encoding="utf-8"))
        return PythonResult(
            ok=bool(payload.get("ok")), stdout=payload.get("stdout", ""), duration_ms=float(payload.get("duration_ms", 0)),
            packages=check.packages, limits_enforced=bool(payload.get("limits_enforced")), result=payload.get("result"),
            error=payload.get("error"), versions=payload.get("versions", {}),
        )
    finally:
        _remove_dir(workdir)


__all__ = ["run_python", "PythonResult", "PythonExecutionError", "PythonRejected"]
