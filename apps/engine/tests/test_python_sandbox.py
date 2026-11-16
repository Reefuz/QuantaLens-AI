import os
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from app.analysis import python_exec
from app.analysis.python_exec import PythonExecutionError, run_python
from app.analysis.python_guard import PythonRejected, validate_python


@pytest.fixture(scope="module")
def df():
    rng = np.random.default_rng(7)
    n = 400
    x = rng.normal(50, 10, n)
    return pd.DataFrame({
        "segment": rng.choice(["A", "B", "C"], n),
        "x": x,
        "y": 2.5 * x + rng.normal(0, 5, n),
        "when": pd.to_datetime("2024-01-01") + pd.to_timedelta(rng.integers(0, 365, n), unit="D"),
    })


# ── static guard (fast) ────────────────────────────────────────────────────

class TestGuardAccepts:
    @pytest.mark.parametrize("code", [
        "result = df['x'].mean()",
        "import numpy as np\nfrom scipy import stats\nresult = stats.pearsonr(df['x'], df['y'])",
        "from sklearn.cluster import KMeans\nfrom sklearn.ensemble import IsolationForest\nresult = 1",
        "result = df.groupby('segment')['x'].agg(['mean','median','std']).reset_index()",
        "def f(v):\n    return v * 2\nresult = df['x'].map(f).sum()",
        "result = {'n': len(df), 'label': f\"rows={len(df):,}\"}",
        "import math, statistics, datetime\nresult = math.sqrt(statistics.mean([1,2,3]))",
        "from sklearn import cluster\nresult = 1",
        "print(df.describe())\nresult = df.shape",
        "r1 = 1\nresult = r1",
    ])
    def test_ok(self, code):
        validate_python(code)

    def test_reports_packages(self):
        assert validate_python("import pandas as pd\nfrom scipy import stats\nimport sklearn.cluster").packages == ["pandas", "scipy", "sklearn"]


class TestGuardRejects:
    @pytest.mark.parametrize("code", [
        "import os",
        "import sys",
        "import subprocess",
        "import socket",
        "import requests",
        "import urllib.request",
        "import pickle",
        "import ctypes",
        "import shutil",
        "import pathlib",
        "import importlib",
        "import builtins",
        "import json",
        "from os import path",
        "from . import x",
        "from pandas import *",
        "import scipy.io",
        "import sklearn.datasets",
        "from sklearn import datasets",
        "open('/etc/passwd')",
        "eval('1+1')",
        "exec('x=1')",
        "compile('1','x','eval')",
        "__import__('os')",
        "getattr(df, '__class__')",
        "setattr(df, 'x', 1)",
        "globals()",
        "vars()",
        "type(df)",
        "input()",
        "df.__class__",
        "df.__class__.__mro__[1].__subclasses__()",
        "().__class__.__bases__[0].__subclasses__()",
        "df._data",
        "'{0.__class__}'.format(df)",
        "'{}'.format_map({})",
        "pd.read_csv('x.csv')",
        "pd.read_pickle('x')",
        "pd.read_sql('select 1', None)",
        "df.to_csv('x.csv')",
        "df.to_pickle('x')",
        "df.to_parquet('x')",
        "df.query('x > 1')",
        "pd.eval('1+1')",
        "df.eval('z = x')",
        "np.load('x.npy')",
        "np.save('x', df)",
        "np.fromfile('x')",
        "np.genfromtxt('x')",
        "np.ctypeslib",
        "pd.io.common",
        "pd.compat",
        "np.testing",
        "df.plot()",
        "df.style",
        "class A: pass",
        "async def f(): pass",
        "def g():\n    yield 1",
        "global x",
        "lambda: (yield)",
        "x = (i for i in range(3)); x.gi_frame",
        "np.os",
        "pd.options.mode.sys",
        "breakpoint()",
        "result = " + "'a'*1 + '" + "x" * 6000 + "'",
    ])
    def test_blocked(self, code):
        with pytest.raises(PythonRejected):
            validate_python(code)

    def test_syntax_error_has_line(self):
        with pytest.raises(PythonRejected, match="line 2"):
            validate_python("x = 1\ny = (")

    def test_empty_and_huge(self):
        for code in ("", "   \n", "x=1\n" * 5000):
            with pytest.raises(PythonRejected):
                validate_python(code)


# ── real execution in the child process ────────────────────────────────────

def test_statistics_match_independent_calculation(df):
    code = """
from scipy import stats
slope, intercept, r, p, se = stats.linregress(df['x'], df['y'])
result = {'mean_x': df['x'].mean(), 'median_x': df['x'].median(), 'std_x': df['x'].std(), 'slope': slope, 'r': r, 'n': len(df)}
"""
    r = run_python(code, df)
    assert r.ok, r.error
    rows = {m: v for m, v in r.result["rows"]}
    ref = np.polyfit(df["x"], df["y"], 1)
    assert rows["mean_x"] == pytest.approx(df["x"].mean()) and rows["std_x"] == pytest.approx(df["x"].std())
    assert rows["slope"] == pytest.approx(ref[0], rel=1e-9) and rows["r"] == pytest.approx(np.corrcoef(df["x"], df["y"])[0, 1])
    assert rows["n"] == 400
    assert "pandas" in r.versions and r.packages == ["scipy"]


def test_dataframe_result_and_groupby(df):
    r = run_python("result = df.groupby('segment')['x'].agg(['count','mean']).reset_index()", df)
    assert r.ok and r.result["kind"] == "table" and r.result["columns"] == ["segment", "count", "mean"]
    expected = df.groupby("segment")["x"].agg(["count", "mean"]).reset_index()
    assert [row[0] for row in r.result["rows"]] == list(expected["segment"])
    assert [row[2] for row in r.result["rows"]] == pytest.approx(list(expected["mean"]))


def test_timestamps_nan_and_numpy_types_are_json_safe(df):
    r = run_python("result = pd.DataFrame({'d': [pd.Timestamp('2024-01-05')], 'v': [np.nan], 'i': [np.int64(3)], 'b': [np.bool_(True)]})", df)
    assert r.ok and r.result["rows"] == [["2024-01-05T00:00:00", None, 3, True]]


def test_print_is_captured_and_capped(df):
    r = run_python("print('hello', 3)\nfor i in range(5000):\n    print('x' * 50)\nresult = 1", df)
    assert r.ok and r.stdout.startswith("hello 3") and len(r.stdout) < 21_000


def test_large_results_are_truncated(df):
    r = run_python("result = pd.DataFrame({'a': range(5000)})", df)
    assert r.result["row_count"] == 5000 and len(r.result["rows"]) == 1000 and r.result["truncated"]


@pytest.mark.parametrize("code", [
    "from sklearn.cluster import KMeans\nkm = KMeans(n_clusters=3, n_init=3, random_state=0).fit(df[['x','y']])\nresult = pd.Series(km.labels_).value_counts().sort_index()",
    "from sklearn.ensemble import IsolationForest\nm = IsolationForest(random_state=0, n_jobs=1).fit(df[['x','y']])\nresult = int((m.predict(df[['x','y']]) == -1).sum())",
    "from sklearn.linear_model import LinearRegression\nm = LinearRegression().fit(df[['x']], df['y'])\nresult = {'r2': m.score(df[['x']], df['y'])}",
])
def test_machine_learning_libraries_work_under_restrictions(df, code):
    r = run_python(code, df)
    assert r.ok, r.error


def test_runtime_errors_are_reported_with_line_number(df):
    r = run_python("x = 1\ny = df['nope']\nresult = y", df)
    assert not r.ok and r.error["type"] == "KeyError" and r.error["line"] == 2


def test_missing_result_is_not_an_error(df):
    r = run_python("x = 1", df)
    assert r.ok and r.result is None


def test_extra_frames_are_available(df):
    r = run_python("result = int(r1['v'].sum())", df, {"r1": pd.DataFrame({"v": [1, 2, 3]})})
    assert r.ok and r.result["value"] == 6


def test_infinite_loop_is_killed(df, monkeypatch):
    monkeypatch.setattr(python_exec, "TIMEOUT_S", 4)
    with pytest.raises(PythonExecutionError, match="longer than 4 seconds"):
        run_python("while True:\n    pass", df)


@pytest.mark.skipif(os.name == "nt", reason="memory rlimit needs POSIX")
def test_normal_analysis_fits_production_memory_budget(df, monkeypatch):
    """Regression: a flat RLIMIT_AS below what pandas/pyarrow already map killed every run on Render."""
    monkeypatch.setattr(python_exec, "MEMORY_MB", 400)
    r = run_python("result = df.groupby(df.columns[0]).size().reset_index(name='n')", df)
    assert r.ok, r.error
    assert r.limits_enforced


@pytest.mark.skipif(os.name == "nt", reason="Linux /proc paths")
@pytest.mark.parametrize("path", ["/proc/self/environ", "/proc/self/cmdline", "/etc/passwd", "/sys/fs/cgroup/memory.max"])
def test_cpu_probe_allowance_does_not_open_other_system_files(df, path):
    r = run_python(f"result = len(pd.read_csv({path!r}, header=None))", df, _validate=False)
    assert not r.ok and r.error["type"] == "PermissionError"


@pytest.mark.skipif(os.name == "nt", reason="memory rlimit needs POSIX")
def test_memory_limit_enforced(df, monkeypatch):
    monkeypatch.setattr(python_exec, "MEMORY_MB", 600)
    r = run_python("result = len(np.ones((4000, 4000, 20)))", df)
    assert not r.ok and r.error["type"] == "MemoryError"


def test_workdirs_are_removed(df):
    before = {p.name for p in Path(tempfile.gettempdir()).glob("ql_py_*")}
    run_python("result = 1", df)
    run_python("raise ValueError('x')", df)
    after = {p.name for p in Path(tempfile.gettempdir()).glob("ql_py_*")}
    assert after <= before, "work directories created by these runs were not removed"


def test_child_environment_has_no_secrets(monkeypatch):
    for k in ("DATABASE_URL", "ANALYTICS_DATABASE_URL", "AI_PROVIDER_API_KEY", "AUTH_SECRET", "ENCRYPTION_KEY"):
        monkeypatch.setenv(k, "super-secret-value")
    env = python_exec._child_env()
    assert not any("secret" in v.lower() for v in env.values())
    assert not set(env) & {"DATABASE_URL", "ANALYTICS_DATABASE_URL", "AI_PROVIDER_API_KEY", "AUTH_SECRET", "ENCRYPTION_KEY"}


# ── defence in depth: the runner's own layers, with the static guard bypassed ──

class TestRunnerDefencesWithoutStaticGuard:
    """These run code the static guard would reject, to show the later layers hold on their own."""

    def run(self, df, code):
        return run_python(code, df, _validate=False)

    def test_import_guard(self, df):
        for mod in ("os", "subprocess", "socket", "pickle", "ctypes"):
            r = self.run(df, f"import {mod}\nresult = 1")
            assert not r.ok and r.error["type"] == "ImportError", mod

    def test_no_dangerous_builtins(self, df):
        for expr in ("open('x')", "eval('1')", "exec('1')", "getattr(df, 'x')", "type(df)", "__import__('os')", "globals()"):
            r = self.run(df, f"result = {expr}")
            assert not r.ok and r.error["type"] in ("NameError", "ImportError"), expr

    def test_cannot_write_files(self, df, tmp_path):
        target = tmp_path / "pwned.csv"
        r = self.run(df, f"df.to_csv(r'{target}')")
        assert not r.ok and r.error["type"] == "PermissionError" and not target.exists()

    def test_cannot_read_files_outside_libraries(self, df, tmp_path):
        secret = tmp_path / "secret.csv"
        secret.write_text("a\nTOP-SECRET\n")
        r = self.run(df, f"result = pd.read_csv(r'{secret}')")
        assert not r.ok and r.error["type"] == "PermissionError" and "TOP-SECRET" not in r.stdout

    def test_cannot_open_network_connections(self, df):
        r = self.run(df, "result = pd.read_csv('http://127.0.0.1:9/x.csv')")
        assert not r.ok and "blocked" in r.error["message"].lower() or "PermissionError" in r.error["type"]

    def test_cannot_spawn_processes(self, df):
        r = self.run(df, "import subprocess\nsubprocess.run(['whoami'])")
        assert not r.ok
