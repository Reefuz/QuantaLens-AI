"""Child-process entry point for model-generated analysis code.  Run as:  python -I sandbox_runner.py <workdir>

Order of operations matters:
  1. import the scientific stack and load the data (needs normal file access)
  2. apply OS resource limits (Linux)
  3. install an audit hook that blocks network, subprocesses, file writes and reads outside library paths
  4. execute the user code with restricted builtins and a guarded __import__
  5. serialise `result` to JSON in the work directory

This file must not import anything from the application package, and it never sees application secrets:
the parent starts it with an almost empty environment.
"""

import ast
import builtins as _builtins
import io
import json
import math
import os
import sys
import time
import traceback

WORKDIR = sys.argv[1]
REQUEST = json.load(open(os.path.join(WORKDIR, "request.json"), encoding="utf-8"))
CODE = open(os.path.join(WORKDIR, "code.py"), encoding="utf-8").read()  # read before the sandbox closes file access
RESULT_PATH = os.path.realpath(os.path.join(WORKDIR, "result.json"))
MAX_STDOUT = 20_000
MAX_ROWS = 1000
MAX_COLS = 60

# ── 1. libraries and data (before restrictions) ────────────────────────────
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import scipy.stats  # noqa: E402,F401

for _name in REQUEST["preload"]:
    try:
        __import__(_name)
    except Exception:  # noqa: BLE001 - optional libraries
        pass

NAMESPACE_FRAMES = {}
for _name, _file in REQUEST["frames"].items():
    NAMESPACE_FRAMES[_name] = pd.read_parquet(os.path.join(WORKDIR, _file))

# ── 2. resource limits (POSIX only) ────────────────────────────────────────
LIMITS_ENFORCED = False
try:
    import resource

    mem = REQUEST["memory_mb"] * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    cpu = REQUEST["timeout_s"] + 2
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1_000_000, 1_000_000))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    LIMITS_ENFORCED = True
except ImportError:
    pass  # Windows development: no `resource` module. Wall-clock timeout still applies.

# ── 3. audit hook ──────────────────────────────────────────────────────────
_READ_ROOTS = tuple(
    os.path.realpath(p)
    for p in {sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix, *[p for p in sys.path if p]}
    if p and os.path.isdir(p) and os.path.realpath(p) != os.path.realpath(os.sep) and os.path.realpath(p) != os.path.realpath(WORKDIR)
)
_ALLOW_RESULT_WRITE = [False]
_DENY_EXACT = {
    "subprocess.Popen", "os.system", "os.posix_spawn", "os.fork", "os.forkpty", "os.startfile", "os.kill", "os.killpg",
    "os.remove", "os.rename", "os.replace", "os.rmdir", "os.mkdir", "os.chmod", "os.chown", "os.truncate", "os.symlink",
    "os.link", "os.utime", "os.putenv", "os.unsetenv", "os.chdir", "os.chroot", "os.setuid", "os.setgid", "os.mkfifo",
    "pickle.find_class", "shutil.rmtree", "shutil.copyfile", "shutil.copytree", "shutil.move", "shutil.chown",
    "shutil.make_archive", "shutil.unpack_archive", "winreg.OpenKey", "winreg.CreateKey", "msvcrt.locking", "webbrowser.open", "sqlite3.connect", "mmap.__new__",
    "sys.settrace", "sys.setprofile", "sys.monitoring.register_callback",
}
_DENY_PREFIXES = ("socket.", "os.exec", "os.spawn", "ftplib.", "smtplib.", "http.client.", "urllib.Request", "telnetlib.", "imaplib.", "poplib.")
_WRITE_FLAGS = getattr(os, "O_WRONLY", 1) | getattr(os, "O_RDWR", 2) | getattr(os, "O_CREAT", 64) | getattr(os, "O_TRUNC", 512) | getattr(os, "O_APPEND", 1024)


def _inside_read_roots(path):
    try:
        real = os.path.realpath(path)
    except Exception:  # noqa: BLE001
        return False
    return real == os.devnull or any(real == r or real.startswith(r + os.sep) for r in _READ_ROOTS)


def _audit(event, args):
    if event == "open":
        path, mode, flags = args[0], args[1], args[2]
        if isinstance(path, int):
            return
        path = os.fsdecode(path)
        writing = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & _WRITE_FLAGS)
        if writing:
            if _ALLOW_RESULT_WRITE[0] and os.path.realpath(path) == RESULT_PATH:
                return
            raise PermissionError("Writing files is not allowed in the analysis sandbox.")
        if not _inside_read_roots(path):
            raise PermissionError("Reading files is not allowed in the analysis sandbox.")
        return
    if event == "ctypes.dlopen":
        # Libraries (BLAS, OpenMP) are loaded by numpy/sklearn themselves. User code cannot import ctypes.
        name = args[0] if args else None
        if isinstance(name, str) and os.path.isabs(name) and not _inside_read_roots(name):
            raise PermissionError("Loading libraries from outside the Python installation is not allowed.")
        return
    if event in _DENY_EXACT or event.startswith(_DENY_PREFIXES):
        raise PermissionError(f"Operation blocked in the analysis sandbox ({event}).")
    if event in ("os.listdir", "os.scandir") and args and args[0] is not None and not isinstance(args[0], int):
        if not _inside_read_roots(os.fsdecode(args[0])):
            raise PermissionError("Listing directories is not allowed in the analysis sandbox.")


sys.addaudithook(_audit)

# ── 4. restricted execution ────────────────────────────────────────────────
_ALLOWED_ROOTS = REQUEST["allowed_imports"]  # {root: [submodules] | null}


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    if level:
        raise ImportError("Relative imports are not allowed.")
    root, _, rest = name.partition(".")
    if root not in _ALLOWED_ROOTS:
        raise ImportError(f"Importing '{name}' is not allowed.")
    subs = _ALLOWED_ROOTS[root]
    if subs is not None and rest and rest.split(".")[0] not in subs:
        raise ImportError(f"Importing '{name}' is not allowed.")
    return __import__(name, globals, locals, fromlist, level)


_stdout = io.StringIO()


def _safe_print(*args, sep=" ", end="\n", **_ignored):
    if _stdout.tell() < MAX_STDOUT:
        _stdout.write(sep.join(str(a) for a in args) + end)


_SAFE_NAMES = (
    "abs all any bool bytes callable chr dict divmod enumerate filter float format frozenset hash int isinstance "
    "issubclass iter len list map max min next ord pow range repr reversed round set slice sorted str sum tuple zip "
    "ArithmeticError AssertionError AttributeError Exception IndexError KeyError LookupError NotImplementedError "
    "OverflowError RuntimeError StopIteration TypeError ValueError ZeroDivisionError FloatingPointError "
    "True False None NotImplemented Ellipsis"
).split()
SAFE_BUILTINS = {n: getattr(_builtins, n) for n in _SAFE_NAMES if hasattr(_builtins, n)}
SAFE_BUILTINS.update(print=_safe_print, __import__=_guarded_import)


# ── 5. result serialisation ────────────────────────────────────────────────
def _scalar(v):
    if v is None or v is pd.NaT:
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return f if math.isfinite(f) else None
    if isinstance(v, (pd.Timestamp,)):
        return v.isoformat()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, (pd.Timedelta, np.timedelta64)):
        return str(v)
    if isinstance(v, str):
        return v[:2000]
    return str(v)[:2000]


def _table(df):
    df = df.copy()
    if not isinstance(df.index, pd.RangeIndex):
        df = df.reset_index()
    df.columns = [str(c) if not isinstance(c, tuple) else " ".join(map(str, c)) for c in df.columns]
    total = len(df)
    cut = df.iloc[:MAX_ROWS, :MAX_COLS]
    rows = [[_scalar(v) for v in row] for row in cut.itertuples(index=False, name=None)]
    return {"kind": "table", "columns": list(cut.columns), "rows": rows, "row_count": total, "truncated": total > MAX_ROWS or df.shape[1] > MAX_COLS}


def _serialise(value):
    if isinstance(value, pd.DataFrame):
        return _table(value)
    if isinstance(value, pd.Series):
        return _table(value.rename(value.name if value.name is not None else "value").to_frame())
    if isinstance(value, dict):
        if value and all(np.isscalar(v) or v is None for v in value.values()):
            return _table(pd.DataFrame({"metric": [str(k) for k in value], "value": [v for v in value.values()]}))
        return {"kind": "dict", "value": {str(k): (_serialise(v) if isinstance(v, (pd.DataFrame, pd.Series)) else _scalar(v)) for k, v in list(value.items())[:200]}}
    if isinstance(value, (list, tuple, np.ndarray)):
        arr = list(value)[:MAX_ROWS]
        if arr and all(isinstance(x, (list, tuple, np.ndarray)) for x in arr):
            return _table(pd.DataFrame(arr))
        return _table(pd.DataFrame({"value": arr}))
    return {"kind": "scalar", "value": _scalar(value)}


def _write(payload):
    _ALLOW_RESULT_WRITE[0] = True
    with open(RESULT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh)
    _ALLOW_RESULT_WRITE[0] = False


def main():
    ns = {"__builtins__": SAFE_BUILTINS, "pd": pd, "np": np, "__name__": "analysis"}
    ns.update(NAMESPACE_FRAMES)
    started = time.perf_counter()
    error = None
    try:
        exec(compile(ast.parse(CODE), "<analysis>", "exec"), ns)  # noqa: S102 - validated, restricted, audited
    except BaseException as exc:  # noqa: BLE001
        tb = traceback.extract_tb(exc.__traceback__)
        line = next((f.lineno for f in reversed(tb) if f.filename == "<analysis>"), None)
        error = {"type": type(exc).__name__, "message": str(exc)[:500], "line": line}
    payload = {
        "ok": error is None,
        "error": error,
        "stdout": _stdout.getvalue(),
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
        "limits_enforced": LIMITS_ENFORCED,
        "versions": {"pandas": pd.__version__, "numpy": np.__version__},
        "result": None,
    }
    if error is None and "result" in ns and ns["result"] is not None:
        try:
            payload["result"] = _serialise(ns["result"])
        except BaseException as exc:  # noqa: BLE001
            payload["ok"], payload["error"] = False, {"type": type(exc).__name__, "message": f"`result` could not be serialised: {str(exc)[:300]}", "line": None}
    _write(payload)


try:
    main()
except MemoryError:
    _ALLOW_RESULT_WRITE[0] = True
    try:
        _write({"ok": False, "error": {"type": "MemoryError", "message": "The analysis ran out of memory.", "line": None}, "stdout": "", "result": None, "limits_enforced": LIMITS_ENFORCED})
    except BaseException:  # noqa: BLE001
        pass
