"""Delete raw/events files older than the retention window (today + yesterday)."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from . import HAVANA_TZ
from .store import data_dir

TZ_HAV = ZoneInfo(HAVANA_TZ)


def today_hav() -> date:
    return datetime.now(TZ_HAV).date()


def prune_old_raw(retain_days: int = 2) -> list[str]:
    """Delete raw/* and events/* JSONL files older than `retain_days` (Havana)."""
    cutoff = today_hav() - timedelta(days=retain_days - 1)
    deleted: list[str] = []
    for sub in ("raw", "events"):
        d = data_dir() / sub
        if not d.exists():
            continue
        for f in d.glob("*.jsonl"):
            try:
                file_date = date.fromisoformat(f.stem)
            except ValueError:
                continue
            if file_date < cutoff:
                f.unlink()
                deleted.append(str(f.relative_to(data_dir())))
    return deleted
