"""Full historical backfill via t.me/s/<channel>?before=<id> pagination.

Runs OFFLINE — do not invoke from CI. Output written directly into data/.
Only daily/ and monthly/ rollups + the latest 2 days of raw/events are kept
afterwards (matching the steady-state retention window).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import CHANNEL
from .aggregate import (
    TZ_HAV,
    daily_rollup,
    havana_date,
    monthly_rollup,
)
from .fetch import fetch_backward, fetch_page, make_client
from .parse import to_event
from .prune import prune_old_raw
from .store import (
    append_jsonl,
    daily_path,
    events_path,
    main_data_path,
    monthly_path,
    raw_path,
    read_json,
    read_jsonl,
    state_path,
    write_json,
    write_jsonl,
)
from .update import build_data_blob


def _today_hav() -> dt.date:
    return datetime.now(TZ_HAV).date()


def backfill(start_before: int | None = None, sleep_s: float = 0.3) -> None:
    """Pull the entire channel history into per-day raw + events files,
    then build daily/monthly rollups. Finally prune raw/events older than 2 days.
    """
    today = _today_hav()
    yesterday = today - timedelta(days=1)

    # Step 1: discover the latest msg id if not given
    if start_before is None:
        with make_client() as client:
            head = fetch_page(client)
        if not head:
            print("no messages on landing page", file=sys.stderr)
            return
        # We want to walk backward from the newest, so we start at latest+1
        latest = max(m.id for m in head)
        start_before = latest + 1
        # write the head messages too
        head_by_day = defaultdict(list)
        for m in head:
            head_by_day[havana_date(m.ts)].append(m.as_dict())
        for day, msgs in head_by_day.items():
            append_jsonl(raw_path(day), msgs)
            append_jsonl(events_path(day), [to_event(m) for m in msgs])

    # Step 2: paginate backward, buffering by day to avoid 1000s of tiny appends
    print(f"backfilling from before={start_before}", flush=True)
    by_day: dict[str, list[dict]] = defaultdict(list)
    total = 0
    last_print = 0
    for msg in fetch_backward(start_before, max_pages=10_000, sleep_s=sleep_s):
        d = havana_date(msg.ts)
        by_day[d].append(msg.as_dict())
        total += 1
        # flush buffer periodically to keep memory bounded
        if total - last_print >= 500:
            print(f"  fetched {total} msgs (oldest ts={msg.ts})", flush=True)
            last_print = total
            _flush_buffer(by_day)
            by_day.clear()

    if by_day:
        _flush_buffer(by_day)
    print(f"backfill: fetched {total} messages", flush=True)

    # Step 3: build daily rollups for every date that has events
    print("building daily rollups...", flush=True)
    days = sorted({f.stem for f in (Path(events_path("X").parent)).glob("*.jsonl")})
    for d in days:
        evs = read_jsonl(events_path(d))
        finalized = date.fromisoformat(d) < today
        roll = daily_rollup(d, evs, finalized=finalized)
        write_json(daily_path(d), roll)
    print(f"daily rollups: {len(days)}", flush=True)

    # Step 4: build monthly rollups
    print("building monthly rollups...", flush=True)
    months = sorted({d[:7] for d in days})
    for month in months:
        dailies = [
            read_json(daily_path(d)) for d in days if d.startswith(month)
        ]
        roll = monthly_rollup(month, dailies)
        write_json(monthly_path(month), roll)
    print(f"monthly rollups: {len(months)}", flush=True)

    # Step 5: build data.json
    write_json(main_data_path(), build_data_blob())

    # Step 6: prune raw/events older than 2 days
    pruned = prune_old_raw(retain_days=2)
    print(f"pruned {len(pruned)} old raw/events files", flush=True)

    # Step 7: state
    state = read_json(state_path(), default={})
    new_state = {
        "last_msg_id": state.get("last_msg_id") or (start_before - 1) if start_before else 0,
        "last_run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "backfill_completed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    # use the latest msg id we ever saw — fetch head one more time
    with make_client() as client:
        head = fetch_page(client)
    if head:
        new_state["last_msg_id"] = max(m.id for m in head)
    write_json(state_path(), new_state)
    print("backfill complete", flush=True)


def _flush_buffer(by_day: dict[str, list[dict]]) -> None:
    """Append buffered msgs+events to disk per day."""
    for day, msgs in by_day.items():
        append_jsonl(raw_path(day), msgs)
        append_jsonl(events_path(day), [to_event(m) for m in msgs])


def main() -> None:
    p = argparse.ArgumentParser(description="Full historical backfill of EELH channel.")
    p.add_argument("--before", type=int, default=None, help="Start pagination before this msg id (default: auto)")
    p.add_argument("--sleep", type=float, default=0.3, help="Per-page sleep seconds (default 0.3)")
    args = p.parse_args()
    backfill(start_before=args.before, sleep_s=args.sleep)


if __name__ == "__main__":
    main()
