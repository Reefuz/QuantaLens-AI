import re

RESERVED = {"_row_id"}
MAX_IDENTIFIER = 60


def to_snake(name: str) -> str:
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name.strip())
    s = re.sub(r"[^0-9A-Za-z]+", "_", s).strip("_").lower()
    return s


def sanitise_columns(headers: list[str]) -> list[str]:
    """Map arbitrary CSV headers to unique, SQL-friendly snake_case identifiers."""
    used: set[str] = set(RESERVED)
    out: list[str] = []
    for i, h in enumerate(headers, start=1):
        base = to_snake(h)[:MAX_IDENTIFIER] or f"column_{i}"
        if base[0].isdigit():
            base = f"col_{base}"
        candidate, n = base, 1
        while candidate in used:
            n += 1
            suffix = f"_{n}"
            candidate = base[: MAX_IDENTIFIER - len(suffix)] + suffix
        used.add(candidate)
        out.append(candidate)
    return out
