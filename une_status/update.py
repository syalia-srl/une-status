"""One incremental update pass. CI runs this every 15 min.

Steps:
1. Fetch the latest channel page.
2. Append new raw msgs (today + yesterday only — older are pruned).
3. Convert to events, append to events/<date>.jsonl.
4. Recompute today's daily rollup (provisional) and yesterday's daily (now finalized if rolled over).
5. Recompute current month's monthly rollup.
6. Rewrite data.json from current state + dailies + monthlies.
7. Prune raw/events files older than retention window.
"""
from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from . import CHANNEL, HAVANA_TZ
from .aggregate import (
    TZ_HAV,
    all_time,
    bucket_events_by_day,
    build_ctes_view,
    current_state,
    daily_rollup,
    havana_date,
    monthly_rollup,
    update_cte_state,
)
from .fetch import fetch_latest
from .parse import to_event
from .prune import prune_old_raw
from .store import (
    append_jsonl,
    cte_state_path,
    data_dir,
    daily_path,
    events_path,
    main_data_path,
    monthly_path,
    raw_path,
    read_json,
    read_jsonl,
    state_path,
    write_json,
)


def _today_hav() -> dt.date:
    return datetime.now(TZ_HAV).date()


def _bucket_msgs_by_day(msgs: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for m in msgs:
        if not m.get("ts"):
            continue
        out[havana_date(m["ts"])].append(m)
    return out


def _affected_months(days: list[str]) -> set[str]:
    return {d[:7] for d in days}


def _list_existing_dates(subdir: str) -> list[str]:
    d = data_dir() / subdir
    if not d.exists():
        return []
    out = []
    for f in d.glob("*.json*"):
        try:
            out.append(f.stem)
        except Exception:
            continue
    return sorted(out)


def _recent_events_for_state(days: int = 2) -> list[dict]:
    """Load the last `days` of events for the current_state calc."""
    today = _today_hav()
    out = []
    for offset in range(days):
        d = (today - timedelta(days=offset)).isoformat()
        out.extend(read_jsonl(events_path(d)))
    return out


def _open_blocks_at_midnight(events: list[dict]) -> set[int]:
    """Return the set of block numbers (1–6) that were still off at the end of
    the day described by `events` (i.e. would carry forward into the next day).

    Uses the last actualizacion_bloques if present; otherwise derives state
    from the greedy inicio/restablecimiento event sequence.
    """
    acts = [e for e in events if e.get("type") == "actualizacion_bloques" and e.get("blocks")]
    if acts:
        latest = max(acts, key=lambda e: e["id"])
        return {blk["bloque"] for blk in latest["blocks"] if blk["hours_off"] * 60 + blk["minutes_off"] > 0}
    state: set[int] = set()
    for e in sorted(events, key=lambda x: x["id"]):
        b = e.get("bloque")
        if not b or b < 1 or b > 6:
            continue
        if e["type"] == "inicio_afectacion":
            state.add(b)
        elif e["type"] == "restablecimiento":
            state.discard(b)
    return state


def update() -> dict:
    state = read_json(state_path(), default={})
    last_seen_id = int(state.get("last_msg_id") or 0)

    raw_latest = fetch_latest()
    new_raw = [m.as_dict() for m in raw_latest if m.id > last_seen_id]
    if new_raw:
        # bucket by Havana date and append
        by_day = _bucket_msgs_by_day(new_raw)
        all_new_events: list[dict] = []
        for day, msgs in by_day.items():
            append_jsonl(raw_path(day), msgs)
            events = [to_event(m) for m in msgs]
            append_jsonl(events_path(day), events)
            all_new_events.extend(events)
        # Merge new unidad_termoelectrica events into the persistent CTE map.
        prior = read_json(cte_state_path(), default={})
        merged = update_cte_state(prior, all_new_events)
        write_json(cte_state_path(), merged)

    # Recompute affected dailies (today + yesterday always, plus any backdated)
    today = _today_hav()
    yesterday = today - timedelta(days=1)
    days_to_refresh = {today.isoformat(), yesterday.isoformat()}
    if new_raw:
        days_to_refresh |= set(_bucket_msgs_by_day(new_raw).keys())

    for d in sorted(days_to_refresh):
        evs = read_jsonl(events_path(d))
        if not evs:
            # if no events file (file pruned) but daily exists, skip
            continue
        # finalized: only if the day is strictly before today (Havana)
        finalized = dt.date.fromisoformat(d) < today
        yesterday_str = (dt.date.fromisoformat(d) - timedelta(days=1)).isoformat()
        prev_evs = read_jsonl(events_path(yesterday_str))
        prior_open_blocks = _open_blocks_at_midnight(prev_evs) if prev_evs else None
        roll = daily_rollup(d, evs, finalized=finalized, prior_open_blocks=prior_open_blocks)
        write_json(daily_path(d), roll)

    # Recompute affected monthlies
    months_to_refresh = _affected_months([today.isoformat(), yesterday.isoformat()])
    if new_raw:
        months_to_refresh |= _affected_months(list(_bucket_msgs_by_day(new_raw).keys()))
    for month in sorted(months_to_refresh):
        dailies = [
            read_json(daily_path(d)) for d in _list_existing_dates("daily") if d.startswith(month)
        ]
        roll = monthly_rollup(month, dailies)
        write_json(monthly_path(month), roll)

    # Build data.json
    data_blob = build_data_blob()
    write_json(main_data_path(), data_blob)

    # Prune raw/events older than retention window
    pruned = prune_old_raw(retain_days=2)

    # Update state
    new_state = {
        "last_msg_id": max([m.id for m in raw_latest] + [last_seen_id]),
        "last_run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "new_msgs": len(new_raw),
        "pruned_files": pruned,
    }
    write_json(state_path(), new_state)
    return new_state


def build_data_blob() -> dict:
    """Compose data.json from rollups + recent events."""
    dailies = []
    for d in _list_existing_dates("daily"):
        try:
            dailies.append(read_json(daily_path(d)))
        except Exception:
            continue
    dailies.sort(key=lambda x: x.get("date", ""))

    monthlies = []
    for m in _list_existing_dates("monthly"):
        try:
            monthlies.append(read_json(monthly_path(m)))
        except Exception:
            continue
    monthlies.sort(key=lambda x: x.get("month", ""))

    today = _today_hav().isoformat()
    yesterday_d = (_today_hav() - timedelta(days=1)).isoformat()
    today_roll = next((d for d in dailies if d.get("date") == today), None)
    yesterday_roll = next((d for d in dailies if d.get("date") == yesterday_d), None)

    # week = last 7 days including today
    week_cutoff = (_today_hav() - timedelta(days=6)).isoformat()
    week_dailies = [d for d in dailies if d.get("date", "") >= week_cutoff]
    week_roll = monthly_rollup("last-7d", week_dailies)
    week_roll["window"] = "7d"
    week_roll.pop("month", None)

    # month = current calendar month
    current_month = _today_hav().strftime("%Y-%m")
    month_roll = next((m for m in monthlies if m.get("month") == current_month), None)

    # all-time
    at = all_time(monthlies)

    # history series
    history = _history_series(dailies, monthlies)

    # current state
    recent_events = _recent_events_for_state(days=2)
    cur = current_state(recent_events)
    # Replace the ctes view with the persistent + assumed-on-after-30d version.
    cte_state = read_json(cte_state_path(), default={})
    cur["ctes"] = build_ctes_view(cte_state, now_iso=cur.get("as_of"))

    # Stamp the most authoritative "last SEN outage" timestamp by looking
    # back through dailies: take the latest day with sen_outage flag and use
    # its date. If current state already has a last_outage_at (within last 2d),
    # prefer that (more precise).
    if not cur.get("sen", {}).get("last_outage_at"):
        for d in reversed(dailies):
            if d.get("sen_outage"):
                cur.setdefault("sen", {})["last_outage_at"] = d["date"]
                break

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_channel": CHANNEL,
        "timezone": HAVANA_TZ,
        "current": cur,
        "day": today_roll or {"date": today, "no_data": True},
        "yesterday": yesterday_roll,
        "week": week_roll,
        "month": month_roll or {"month": current_month, "no_data": True},
        "all_time": at,
        "history": history,
        "meta": {
            "daily_count": len(dailies),
            "monthly_count": len(monthlies),
            "earliest_date": dailies[0]["date"] if dailies else None,
            "latest_date": dailies[-1]["date"] if dailies else None,
        },
    }


def _history_series(dailies: list[dict], monthlies: list[dict]) -> dict:
    last_30 = dailies[-30:]
    last_180 = dailies[-180:]

    # Per-CTE all-time offline-days breakdown
    from collections import Counter
    cte_offline_min: Counter = Counter()
    cte_outage_days: Counter = Counter()
    for d in dailies:
        for cte, m in (d.get("cte_offline_minutes") or {}).items():
            cte_offline_min[cte] += m
            if m > 0:
                cte_outage_days[cte] += 1

    return {
        "daily_peak_mw_last_30d": [
            {"date": d["date"], "peak_mw": d.get("peak_mw_affected")}
            for d in last_30
        ],
        "daily_outage_minutes_last_30d": [
            {"date": d["date"], "minutes": d.get("total_block_outage_minutes") or 0}
            for d in last_30
        ],
        "daily_peak_mw_last_180d": [
            {"date": d["date"], "peak_mw": d.get("peak_mw_affected")}
            for d in last_180
        ],
        "monthly_max_peak_mw": [
            {"month": m["month"], "max_peak_mw": m.get("max_peak_mw")}
            for m in monthlies
        ],
        "monthly_total_outage_minutes": [
            {"month": m["month"], "minutes": sum((m.get("total_block_outage_minutes") or {}).values())}
            for m in monthlies
        ],
        "sen_outage_days_total": sum(1 for d in dailies if d.get("sen_outage")),
        "sen_outage_days_last_30d": sum(1 for d in last_30 if d.get("sen_outage")),
        "sen_collapse_total": sum(d.get("sen_collapse_count", 0) for d in dailies),
        "sen_collapse_last_30d": sum(d.get("sen_collapse_count", 0) for d in last_30),
        "daf_total": sum(d.get("daf_count", 0) for d in dailies),
        "daf_last_30d": sum(d.get("daf_count", 0) for d in last_30),
        "cte_offline_minutes_total": dict(cte_offline_min),
        "cte_offline_days_total": dict(cte_outage_days),
    }


def main() -> None:
    res = update()
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
