"""Safe CSV ingestion.

Never trusts the filename or content type. Rejects binary and archive formats by content,
detects encoding and delimiter, tolerates ragged rows, and returns every value as text.
"""

from __future__ import annotations

import csv
import io
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

MAX_COLUMNS = 200
MAX_ROWS = 1_000_000
_CANDIDATE_DELIMITERS = [",", ";", "\t", "|"]
_SIGNATURES: list[tuple[bytes, str]] = [
    (b"PK\x03\x04", "an Excel or zip archive. Export the sheet as CSV first."),
    (b"%PDF", "a PDF document."),
    (b"\x89PNG", "an image."),
    (b"\xff\xd8\xff", "an image."),
    (b"GIF8", "an image."),
    (b"MZ", "an executable file."),
    (b"\x7fELF", "an executable file."),
    (b"\xd0\xcf\x11\xe0", "a legacy Excel/Word document. Export as CSV first."),
]


class CsvError(ValueError):
    """Raised with a message that is safe to show to the user."""


@dataclass
class CsvReadResult:
    frame: pd.DataFrame  # object dtype, strings or None
    original_headers: list[str]
    encoding: str
    delimiter: str
    warnings: list[str] = field(default_factory=list)
    skipped_rows: int = 0


def sanitise_filename(name: str | None) -> str:
    base = (name or "upload.csv").replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r"[\x00-\x1f\x7f]", "", base).strip()
    return (base or "upload.csv")[:255]


def _check_signature(head: bytes) -> None:
    for magic, kind in _SIGNATURES:
        if head.startswith(magic):
            raise CsvError(f"This file is {kind}")
    if b"\x00" in head:
        raise CsvError("This file looks binary, not like a CSV text file.")


def _decode(raw: bytes) -> tuple[str, str]:
    try:
        return raw.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace"), "cp1252"


def detect_delimiter(text: str) -> str:
    lines = [ln for ln in text[:65536].splitlines() if ln.strip()][:20]
    if not lines:
        return ","
    best, best_score = ",", 0.0
    for d in _CANDIDATE_DELIMITERS:
        counts = [ln.count(d) for ln in lines]
        median = statistics.median(counts)
        if median < 1:
            continue
        consistency = sum(1 for c in counts if c == median) / len(counts)
        score = median * consistency
        if consistency >= 0.6 and score > best_score:
            best, best_score = d, score
    return best


def unique_headers(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    out = []
    for i, h in enumerate(headers, start=1):
        name = (h or "").strip() or f"column_{i}"
        key = name.lower()
        seen[key] = seen.get(key, 0) + 1
        out.append(name if seen[key] == 1 else f"{name}_{seen[key]}")
    return out


def read_csv_file(path: Path) -> CsvReadResult:
    raw = path.read_bytes()
    if not raw.strip():
        raise CsvError("The file is empty.")
    _check_signature(raw[:8192])
    text, encoding = _decode(raw)
    del raw
    if "\x00" in text:
        raise CsvError("This file contains binary data, not just CSV text.")
    delimiter = detect_delimiter(text)

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        header = next(reader)
    except (StopIteration, csv.Error) as exc:
        raise CsvError("Could not read a header row from this file.") from exc
    if len(header) > MAX_COLUMNS:
        raise CsvError(f"Too many columns ({len(header)}). The limit is {MAX_COLUMNS}.")
    headers = unique_headers(header)
    ncols = len(headers)

    rows: list[list[str | None]] = []
    skipped_long = padded_short = blank = 0
    try:
        for row in reader:
            if not row or all(not c.strip() for c in row):
                blank += 1
                continue
            if len(row) > ncols:
                skipped_long += 1
                continue
            if len(row) < ncols:
                padded_short += 1
                row = row + [""] * (ncols - len(row))
            rows.append([c if c != "" else None for c in row])
            if len(rows) > MAX_ROWS:
                raise CsvError(f"Too many rows. The limit is {MAX_ROWS:,}.")
    except csv.Error as exc:
        raise CsvError("The file is not valid CSV (malformed quoting).") from exc

    if not rows:
        raise CsvError("The file has a header but no data rows.")

    warnings = []
    if skipped_long:
        warnings.append(f"{skipped_long:,} rows had more fields than the header and were skipped.")
    if padded_short:
        warnings.append(f"{padded_short:,} rows had fewer fields than the header; missing fields were left empty.")
    if blank:
        warnings.append(f"{blank:,} blank lines were ignored.")
    if encoding != "utf-8":
        warnings.append("The file is not UTF-8. It was read as Windows-1252; check that accents look right.")

    frame = pd.DataFrame(rows, columns=headers, dtype=object)
    return CsvReadResult(
        frame=frame,
        original_headers=headers,
        encoding=encoding,
        delimiter=delimiter,
        warnings=warnings,
        skipped_rows=skipped_long,
    )
