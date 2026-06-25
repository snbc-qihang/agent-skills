"""File writing helpers used by generator modules."""

from __future__ import annotations

import json
from pathlib import Path


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def write_json(path: Path, data: object) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2))
