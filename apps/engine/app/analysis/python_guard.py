"""Static validation of model-generated Python (first layer of the restricted runner).

This narrows what analysis code can express. It is not, on its own, a security boundary:
the runner adds restricted builtins, an import guard, an interpreter audit hook and OS limits.
See SECURITY.md for what the combination does and does not protect against.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

MAX_CODE_CHARS = 10_000
MAX_NUMERIC_LITERALS = 40  # data must come from `df` or a stored result, not be retyped into the code

# Top-level modules, with the submodules that may be imported from them (None = any submodule).
ALLOWED_IMPORTS: dict[str, frozenset[str] | None] = {
    "pandas": None,
    "numpy": None,
    "math": None,
    "statistics": None,
    "datetime": None,
    "collections": None,
    "itertools": None,
    "functools": None,
    "operator": None,
    "decimal": None,
    "fractions": None,
    "calendar": None,
    "re": None,
    "typing": None,
    "warnings": None,
    "scipy": frozenset({"stats", "optimize", "special", "cluster", "signal", "spatial", "interpolate"}),
    "sklearn": frozenset({
        "cluster", "linear_model", "ensemble", "preprocessing", "metrics", "decomposition", "model_selection",
        "tree", "neighbors", "mixture", "impute", "feature_selection", "svm", "naive_bayes", "pipeline",
        "covariance", "manifold", "compose", "base", "utils",
    }),
}

BANNED_NAMES = frozenset({
    "__import__", "eval", "exec", "compile", "open", "input", "breakpoint", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "type", "object", "super", "help", "exit", "quit", "memoryview",
    "classmethod", "staticmethod", "property", "__builtins__", "__loader__", "__spec__", "__build_class__",
})

# Attribute names that reach I/O, code execution, process control or interpreter internals.
BANNED_ATTRS = frozenset({
    "eval", "query", "format", "format_map", "vformat", "mro", "system", "popen", "spawn", "fork",
    "io", "os", "sys", "subprocess", "socket", "builtins", "importlib", "ctypes", "ctypeslib", "pickle",
    "cloudpickle", "joblib", "shutil", "pathlib", "tempfile", "urllib", "requests", "http", "compat",
    "testing", "f2py", "distutils", "memmap", "fromfile", "tofile", "plotting", "plot", "style",
    "gi_frame", "gi_code", "gi_yieldfrom", "cr_frame", "cr_code", "ag_frame", "ag_code",
    "tb_frame", "tb_next", "f_back", "f_globals", "f_locals", "f_builtins", "f_code", "co_code",
    "func_globals", "get_option", "set_option", "option_context", "reset_option",
    "genfromtxt", "fromregex", "recfromcsv", "recfromtxt", "DataSource", "datasets", "ExcelFile", "ExcelWriter", "HDFStore", "StataReader",
    "to_pickle", "to_csv", "to_excel", "to_parquet", "to_hdf", "to_sql", "to_feather", "to_orc", "to_stata",
    "to_gbq", "to_clipboard", "to_latex", "to_html", "to_xml", "to_json", "to_markdown",
})
BANNED_ATTR_PREFIXES = ("read_", "load", "save", "dump", "__", "_")

_BANNED_NODES = (
    ast.ClassDef, ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith, ast.Yield, ast.YieldFrom,
    ast.Global, ast.Nonlocal,
)


class PythonRejected(ValueError):
    """The code is not permitted. The message is safe to show to the user and the model."""


@dataclass
class PythonCheck:
    packages: list[str]
    uses_frames: list[str]


def _module_allowed(name: str) -> bool:
    root, _, rest = name.partition(".")
    if root not in ALLOWED_IMPORTS:
        return False
    subs = ALLOWED_IMPORTS[root]
    if subs is None or not rest:
        return True
    return rest.split(".")[0] in subs


def module_allowed(name: str) -> bool:
    """Used by the runner's runtime import guard as well."""
    return _module_allowed(name)


def validate_python(code: str) -> PythonCheck:
    if not code or not code.strip():
        raise PythonRejected("The code is empty.")
    if len(code) > MAX_CODE_CHARS:
        raise PythonRejected(f"The code is too long (limit {MAX_CODE_CHARS:,} characters).")
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as exc:
        raise PythonRejected(f"Syntax error on line {exc.lineno}: {exc.msg}") from exc

    literals = sum(1 for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)) and not isinstance(n.value, bool))
    if literals > MAX_NUMERIC_LITERALS:
        raise PythonRejected(f"The code contains {literals} numeric literals. Do not retype data into the code: use `df` for the dataset, or `r1`, `r2` for earlier results.")
    packages: set[str] = set()
    frames: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, _BANNED_NODES):
            raise PythonRejected(f"{type(node).__name__} is not allowed here. Use plain functions and expressions.")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not _module_allowed(alias.name):
                    raise PythonRejected(f"Importing '{alias.name}' is not allowed.")
                packages.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module or not _module_allowed(node.module):
                raise PythonRejected(f"Importing from '{node.module or '.'}' is not allowed.")
            root, _, rest = node.module.partition(".")
            subs = ALLOWED_IMPORTS[root]
            # `from sklearn import cluster` imports a submodule by name
            if subs is not None and not rest:
                for alias in node.names:
                    if alias.name not in subs and alias.name != "*":
                        raise PythonRejected(f"Importing '{alias.name}' from '{root}' is not allowed.")
            if any(alias.name == "*" for alias in node.names):
                raise PythonRejected("Wildcard imports are not allowed.")
            packages.add(root)
        elif isinstance(node, ast.Name):
            if node.id in BANNED_NAMES or node.id.startswith("__"):
                raise PythonRejected(f"'{node.id}' is not allowed.")
            if node.id.startswith("r") and node.id[1:].isdigit():
                frames.add(node.id)
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if attr in BANNED_ATTRS or attr.startswith(BANNED_ATTR_PREFIXES):
                if attr.startswith("_"):
                    raise PythonRejected("Accessing private or dunder attributes is not allowed.")
                raise PythonRejected(f"The attribute '.{attr}' is not allowed (file, system and code-execution access is blocked).")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) > 5000:
            raise PythonRejected("String literals longer than 5,000 characters are not allowed.")
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in BANNED_NAMES:
            raise PythonRejected(f"'{node.func.id}()' is not allowed.")
    return PythonCheck(packages=sorted(packages), uses_frames=sorted(frames))
