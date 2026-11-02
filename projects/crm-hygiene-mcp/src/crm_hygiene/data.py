"""Read-only access to CSV exports inside one allowed directory.

The server never takes arbitrary file paths from the model. It only reads
``<name>.csv`` files that live directly inside the configured data directory,
which keeps an agent from wandering the filesystem.
"""

from __future__ import annotations

import csv
import os
import re
from pathlib import Path

DATA_DIR_ENV = "CRM_HYGIENE_DATA_DIR"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")


class DataAccessError(ValueError):
    """Raised when a requested export is outside the allowed scope or missing."""


def data_dir() -> Path:
    raw = os.environ.get(DATA_DIR_ENV)
    if not raw:
        raise DataAccessError(f"Set {DATA_DIR_ENV} to the folder that holds your CRM CSV exports.")
    path = Path(raw).expanduser().resolve()
    if not path.is_dir():
        raise DataAccessError(f"{DATA_DIR_ENV} points to a folder that does not exist: {path}")
    return path


def list_exports() -> list[dict]:
    root = data_dir()
    out = []
    for file in sorted(root.glob("*.csv")):
        with file.open(encoding="utf-8", newline="") as fh:
            reader = csv.reader(fh)
            header = next(reader, [])
            rows = sum(1 for _ in reader)
        out.append({"name": file.stem, "columns": header, "rows": rows})
    return out


def load_export(name: str) -> list[dict[str, str]]:
    if not _SAFE_NAME.match(name or ""):
        raise DataAccessError(f"Invalid export name {name!r}: use the bare file name without extension.")
    root = data_dir()
    file = (root / f"{name}.csv").resolve()
    if file.parent != root or not file.is_file():
        raise DataAccessError(f"Export {name!r} not found in the data directory.")
    with file.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))
