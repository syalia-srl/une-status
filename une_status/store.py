"""File I/O helpers for the data/ tree. Append-only JSONL for raw/events,
JSON files for rollups and state.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable


def repo_root() -> Path:
    # une_status/store.py → repo root is parent of une_status/
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    return repo_root() / "data"


def _ensure(p: Path) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def write_jsonl(path: Path, items: Iterable[dict]) -> None:
    lines = [json.dumps(it, ensure_ascii=False) for it in items]
    _ensure(path).write_text("\n".join(lines) + ("\n" if lines else ""))


def append_jsonl(path: Path, items: Iterable[dict]) -> None:
    """Append new items to a JSONL file, deduplicating by `id`."""
    existing = read_jsonl(path)
    seen = {x.get("id") for x in existing if "id" in x}
    new = [it for it in items if it.get("id") not in seen]
    if not new:
        return
    all_items = existing + new
    all_items.sort(key=lambda x: x.get("id", 0))
    write_jsonl(path, all_items)


def read_json(path: Path, default=None):
    if not path.exists():
        return default if default is not None else {}
    return json.loads(path.read_text())


def write_json(path: Path, obj, indent: int | None = 2) -> None:
    _ensure(path).write_text(
        json.dumps(obj, ensure_ascii=False, indent=indent, sort_keys=False) + "\n"
    )


# Conventions
def state_path() -> Path:
    return data_dir() / "state.json"


def main_data_path() -> Path:
    return data_dir() / "data.json"


def raw_path(date_str: str) -> Path:
    return data_dir() / "raw" / f"{date_str}.jsonl"


def events_path(date_str: str) -> Path:
    return data_dir() / "events" / f"{date_str}.jsonl"


def daily_path(date_str: str) -> Path:
    return data_dir() / "daily" / f"{date_str}.json"


def monthly_path(month_str: str) -> Path:
    return data_dir() / "monthly" / f"{month_str}.json"
