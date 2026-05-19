"""Rollup events into daily, monthly, all-time, and current-state structures.

Daily rollups are immutable once finalized; monthly are derived from dailies.
Current state is computed each run from the most recent events.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from . import HAVANA_TZ

TZ_HAV = ZoneInfo(HAVANA_TZ)


def _parse_ts(s: str) -> datetime:
    """Parse ISO 8601 with Z or offset."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def havana_date(ts: str) -> str:
    """Map a UTC ISO timestamp to its Havana civil date (YYYY-MM-DD)."""
    return _parse_ts(ts).astimezone(TZ_HAV).date().isoformat()


def bucket_events_by_day(events: Iterable[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        out[havana_date(e["ts"])].append(e)
    return out


def daily_rollup(day: str, events: list[dict], finalized: bool) -> dict:
    """Build the daily rollup for `day` from its events (sorted by id)."""
    events = sorted(events, key=lambda e: e["id"])
    by_type = Counter(e["type"] for e in events)

    # peak MW + time: prefer nota_diaria, fallback to actualizacion_bloques
    peak_mw = 0
    peak_time = None
    notas = [e for e in events if e["type"] == "nota_diaria"]
    for n in notas:
        if "max_affected_mw" in n and n["max_affected_mw"] > peak_mw:
            peak_mw = n["max_affected_mw"]
            peak_time = n.get("max_affected_clock")
    # fallback: max of actualizacion_bloques.total_mw
    if peak_mw == 0:
        for e in events:
            if e["type"] == "actualizacion_bloques" and "total_mw" in e:
                if e["total_mw"] > peak_mw:
                    peak_mw = e["total_mw"]
                    peak_time = _parse_ts(e["ts"]).astimezone(TZ_HAV).strftime("%H:%M")

    interruption_minutes = sum(n.get("interruption_minutes", 0) for n in notas)
    emergency_mw = max((n.get("emergency_mw", 0) for n in notas), default=0)

    # block outage minutes: prefer the latest actualizacion_bloques of the day
    # (which carries running cumulative totals), fall back to greedy event pairing.
    block_minutes = _block_outage_from_latest_actualizacion(events) or _block_outage_minutes(events, day)

    # averias by municipio
    municipios: Counter = Counter()
    for e in events:
        if e["type"] == "averias":
            for a in e.get("averias", []):
                municipios[a.get("municipio", "Desconocido")] += 1
        elif e["type"] == "disparo_circuito":
            if mun := e.get("municipio"):
                municipios[mun] += 1

    daf_count = by_type.get("daf", 0)
    sen_collapse_count = by_type.get("desconexion_total_sen", 0)

    # SEN outage minutes: ONLY full-grid collapse events count. DAF is a
    # partial freq event and does not constitute a SEN outage.
    sen_outage_minutes = _sen_outage_minutes(events, day)
    sen_outage = sen_collapse_count > 0

    partial_sen_collapse_count = by_type.get("caida_parcial_sen", 0)
    partial_sen_reconnect_count = by_type.get("reconexion_parcial_sen", 0)
    partial_sen_outage_minutes = _partial_sen_outage_minutes(events, day)

    # CTE offline minutes per canonical id
    cte_offline_minutes = _cte_offline_minutes(events, day)

    return {
        "date": day,
        "finalized": finalized,
        "peak_mw_affected": peak_mw or None,
        "peak_time": peak_time,
        "interruption_minutes": interruption_minutes or None,
        "emergency_mw": emergency_mw or None,
        "block_outage_minutes": block_minutes,
        "total_block_outage_minutes": sum(block_minutes.values()),
        "daf_count": daf_count,
        "sen_collapse_count": sen_collapse_count,
        "sen_outage_minutes": sen_outage_minutes,
        "sen_outage": sen_outage,
        "partial_sen_collapse_count": partial_sen_collapse_count,
        "partial_sen_reconnect_count": partial_sen_reconnect_count,
        "partial_sen_outage_minutes": partial_sen_outage_minutes,
        "cte_offline_minutes": cte_offline_minutes,
        "averias_count_by_municipio": dict(municipios.most_common()),
        "averias_total": sum(municipios.values()),
        "source_msg_count": len(events),
        "by_type_counts": dict(by_type),
    }


def _sen_outage_minutes(events: list[dict], day: str) -> int:
    """Greedy pair `desconexion_total_sen` with the next `restablecimiento_sen`.
    Open intervals at end of Havana day count up to midnight. DAF events are
    explicitly NOT included — a DAF is a partial frequency trip, not a
    national blackout.
    """
    total = 0
    open_start: datetime | None = None
    end_of_day = datetime.fromisoformat(day).replace(tzinfo=TZ_HAV) + timedelta(days=1)
    for e in sorted(events, key=lambda x: x["id"]):
        ts = _parse_ts(e["ts"]).astimezone(TZ_HAV)
        if e["type"] == "desconexion_total_sen" and open_start is None:
            open_start = ts
        elif e["type"] == "restablecimiento_sen" and open_start is not None:
            total += int(max(0, (ts - open_start).total_seconds() / 60))
            open_start = None
    if open_start is not None:
        total += int(max(0, (end_of_day - open_start).total_seconds() / 60))
    return total


def _partial_sen_outage_minutes(events: list[dict], day: str) -> int:
    """Greedy pair `caida_parcial_sen` with the next `reconexion_parcial_sen`.
    Open intervals at end of Havana day count up to midnight.
    """
    total = 0
    open_start: datetime | None = None
    end_of_day = datetime.fromisoformat(day).replace(tzinfo=TZ_HAV) + timedelta(days=1)
    for e in sorted(events, key=lambda x: x["id"]):
        ts = _parse_ts(e["ts"]).astimezone(TZ_HAV)
        if e["type"] == "caida_parcial_sen" and open_start is None:
            open_start = ts
        elif e["type"] == "reconexion_parcial_sen" and open_start is not None:
            total += int(max(0, (ts - open_start).total_seconds() / 60))
            open_start = None
    if open_start is not None:
        total += int(max(0, (end_of_day - open_start).total_seconds() / 60))
    return total


def _cte_offline_minutes(events: list[dict], day: str) -> dict[str, int]:
    """Per-CTE total offline minutes for `day`. Greedy pair unit on/off.
    Track by (cte_id, unidad). Open intervals count to end-of-day.
    """
    out: dict[str, int] = {}
    open_intervals: dict[tuple[str, int], datetime] = {}
    end_of_day = datetime.fromisoformat(day).replace(tzinfo=TZ_HAV) + timedelta(days=1)
    for e in sorted(events, key=lambda x: x["id"]):
        if e.get("type") != "unidad_termoelectrica":
            continue
        cte = e.get("cte_id")
        unit = e.get("unidad")
        state = e.get("state")
        if not cte or unit is None or not state:
            continue
        ts = _parse_ts(e["ts"]).astimezone(TZ_HAV)
        key = (cte, unit)
        if state == "offline" and key not in open_intervals:
            open_intervals[key] = ts
        elif state == "online" and key in open_intervals:
            delta = int(max(0, (ts - open_intervals[key]).total_seconds() / 60))
            out[cte] = out.get(cte, 0) + delta
            del open_intervals[key]
    for (cte, _), start in open_intervals.items():
        delta = int(max(0, (end_of_day - start).total_seconds() / 60))
        out[cte] = out.get(cte, 0) + delta
    return out


def _block_outage_from_latest_actualizacion(events: list[dict]) -> dict[str, int]:
    """Read the latest actualizacion_bloques of the day; its hours_off/minutes_off
    fields are running cumulative totals per bloque.
    """
    actualizaciones = [e for e in events if e["type"] == "actualizacion_bloques" and e.get("blocks")]
    if not actualizaciones:
        return {}
    latest = max(actualizaciones, key=lambda e: e["id"])
    out = {str(b): 0 for b in range(1, 7)}
    for blk in latest.get("blocks", []):
        bn = str(blk["bloque"])
        out[bn] = blk["hours_off"] * 60 + blk["minutes_off"]
    return out


def _block_outage_minutes(events: list[dict], day: str) -> dict[str, int]:
    """For each bloque (1–6), sum minutes between inicio_afectacion and
    restablecimiento events on `day`. If a bloque starts off mid-day with no
    matching restablecimiento by day end (Havana midnight), count to midnight.
    """
    minutes: dict[str, int] = {str(b): 0 for b in range(1, 7)}
    state: dict[int, datetime] = {}  # bloque -> start_ts
    end_of_day = datetime.fromisoformat(day).replace(tzinfo=TZ_HAV) + timedelta(days=1)

    for e in sorted(events, key=lambda x: x["id"]):
        b = e.get("bloque")
        if not b or b < 1 or b > 6:
            continue
        ts = _parse_ts(e["ts"]).astimezone(TZ_HAV)
        if e["type"] == "inicio_afectacion":
            state[b] = ts
        elif e["type"] == "restablecimiento":
            if b in state:
                delta = (ts - state[b]).total_seconds() / 60
                minutes[str(b)] += int(max(0, delta))
                del state[b]
    # any block still off at end of day
    for b, start in state.items():
        delta = (end_of_day - start).total_seconds() / 60
        minutes[str(b)] += int(max(0, delta))
    return minutes


def monthly_rollup(month: str, dailies: list[dict]) -> dict:
    """Aggregate a list of daily rollups into a month."""
    if not dailies:
        return {"month": month, "finalized": False, "dailies_count": 0}

    peak_mws = [d["peak_mw_affected"] for d in dailies if d.get("peak_mw_affected")]
    interruptions = [d.get("interruption_minutes") or 0 for d in dailies]
    block_totals: Counter = Counter()
    for d in dailies:
        for b, m in (d.get("block_outage_minutes") or {}).items():
            block_totals[b] += m
    mun_totals: Counter = Counter()
    for d in dailies:
        for m, n in (d.get("averias_count_by_municipio") or {}).items():
            mun_totals[m] += n

    cte_totals: Counter = Counter()
    for d in dailies:
        for cte, m in (d.get("cte_offline_minutes") or {}).items():
            cte_totals[cte] += m

    return {
        "month": month,
        "finalized": all(d.get("finalized") for d in dailies),
        "dailies_count": len(dailies),
        "avg_peak_mw": round(sum(peak_mws) / len(peak_mws), 1) if peak_mws else None,
        "max_peak_mw": max(peak_mws, default=None),
        "total_interruption_minutes": sum(interruptions),
        "total_block_outage_minutes": dict(block_totals),
        "total_emergency_mw_sum": sum(d.get("emergency_mw") or 0 for d in dailies),
        "averias_count_by_municipio": dict(mun_totals.most_common()),
        "averias_total": sum(mun_totals.values()),
        "daf_total": sum(d.get("daf_count", 0) for d in dailies),
        "sen_collapse_total": sum(d.get("sen_collapse_count", 0) for d in dailies),
        "sen_outage_days": sum(1 for d in dailies if d.get("sen_outage")),
        "sen_outage_minutes_total": sum(d.get("sen_outage_minutes", 0) for d in dailies),
        "partial_sen_collapse_total": sum(d.get("partial_sen_collapse_count", 0) for d in dailies),
        "partial_sen_outage_minutes_total": sum(d.get("partial_sen_outage_minutes", 0) for d in dailies),
        "cte_offline_minutes_total": dict(cte_totals),
    }


def all_time(monthlies: list[dict]) -> dict:
    if not monthlies:
        return {"finalized": False}
    peak_mws = [m["max_peak_mw"] for m in monthlies if m.get("max_peak_mw")]
    block_totals: Counter = Counter()
    for m in monthlies:
        for b, mi in (m.get("total_block_outage_minutes") or {}).items():
            block_totals[b] += mi
    mun_totals: Counter = Counter()
    for m in monthlies:
        for mn, n in (m.get("averias_count_by_municipio") or {}).items():
            mun_totals[mn] += n
    cte_totals: Counter = Counter()
    for m in monthlies:
        for cte, mins in (m.get("cte_offline_minutes_total") or {}).items():
            cte_totals[cte] += mins

    return {
        "months_count": len(monthlies),
        "max_peak_mw": max(peak_mws, default=None),
        "total_interruption_minutes": sum(m.get("total_interruption_minutes", 0) for m in monthlies),
        "total_block_outage_minutes": dict(block_totals),
        "averias_total": sum(mun_totals.values()),
        "averias_top_municipios": dict(mun_totals.most_common(15)),
        "daf_total": sum(m.get("daf_total", 0) for m in monthlies),
        "sen_collapse_total": sum(m.get("sen_collapse_total", 0) for m in monthlies),
        "sen_outage_days_total": sum(m.get("sen_outage_days", 0) for m in monthlies),
        "sen_outage_minutes_total": sum(m.get("sen_outage_minutes_total", 0) for m in monthlies),
        "partial_sen_collapse_total": sum(m.get("partial_sen_collapse_total", 0) for m in monthlies),
        "partial_sen_outage_minutes_total": sum(m.get("partial_sen_outage_minutes_total", 0) for m in monthlies),
        "cte_offline_minutes_total": dict(cte_totals),
    }


CTE_REGISTRY_IDS: list[tuple[str, str]] = [
    ("felton", "Lidio Ramón Pérez (Felton)"),
    ("guiteras", "Antonio Guiteras"),
    ("maximo-gomez", "Máximo Gómez (Mariel)"),
    ("cespedes", "Carlos M. de Céspedes (Cienfuegos)"),
    ("nuevitas", "10 de Octubre (Nuevitas)"),
    ("tallapiedra", "Otto Parellada (Tallapiedra)"),
    ("guevara", "Ernesto Guevara (Santa Cruz)"),
    ("rente", "Antonio Maceo (Renté)"),
]


def update_cte_state(prior: dict, events: Iterable[dict]) -> dict:
    """Merge unidad_termoelectrica events into the persistent CTE state map.

    Keeps per-unit latest state and per-plant timestamps of the latest event,
    online event, offline event, and aggregate state. Idempotent: replaying
    the same events leaves the map unchanged.
    """
    state = dict((prior or {}).get("ctes") or {})
    for e in events:
        if e.get("type") != "unidad_termoelectrica":
            continue
        cte = e.get("cte_id")
        unit = e.get("unidad")
        st = e.get("state")
        ts = e.get("ts")
        if not (cte and unit is not None and st and ts):
            continue
        entry = state.setdefault(cte, {
            "name": e.get("cte_name") or cte,
            "units": {},
            "last_seen_at": None,
            "last_online_at": None,
            "last_offline_at": None,
            "last_change_at": None,
            "state": None,
        })
        if e.get("cte_name"):
            entry["name"] = e["cte_name"]
        u_key = str(unit)
        u = entry["units"].setdefault(u_key, {"state": None, "since": None})
        if u["since"] is None or ts >= u["since"]:
            prev = u["state"]
            u["state"] = st
            u["since"] = ts
            if prev != st:
                if not entry.get("last_change_at") or ts > entry["last_change_at"]:
                    entry["last_change_at"] = ts
        if not entry["last_seen_at"] or ts > entry["last_seen_at"]:
            entry["last_seen_at"] = ts
        if st == "online" and (not entry.get("last_online_at") or ts > entry["last_online_at"]):
            entry["last_online_at"] = ts
        if st == "offline" and (not entry.get("last_offline_at") or ts > entry["last_offline_at"]):
            entry["last_offline_at"] = ts

    for entry in state.values():
        online = sum(1 for u in entry["units"].values() if u["state"] == "online")
        offline = sum(1 for u in entry["units"].values() if u["state"] == "offline")
        if online > 0 and offline == 0:
            entry["state"] = "online"
        elif offline > 0 and online == 0:
            entry["state"] = "offline"
        elif online > 0 and offline > 0:
            entry["state"] = "partial"
        else:
            entry["state"] = None
    return {"ctes": state}


def build_ctes_view(cte_state: dict, now_iso: str | None = None, assume_after_days: int = 30) -> list[dict]:
    """Return the public-facing CTEs list. For each plant in the canonical
    registry: use the observed state if last_seen_at is within
    `assume_after_days`; otherwise mark `assumed_online` with lighter color.
    Plants we have never heard of also fall through to `assumed_online`.
    """
    now = _parse_ts(now_iso) if now_iso else datetime.now(timezone.utc)
    cutoff = now - timedelta(days=assume_after_days)
    state = (cte_state or {}).get("ctes") or {}
    seen_ids: set[str] = set()
    out: list[dict] = []
    for cte_id, default_name in CTE_REGISTRY_IDS:
        entry = state.get(cte_id)
        view = _cte_view(cte_id, entry, default_name, cutoff)
        out.append(view)
        seen_ids.add(cte_id)
    # tail: any other CTE that appeared in messages but isn't in the registry
    for cte_id, entry in state.items():
        if cte_id in seen_ids:
            continue
        out.append(_cte_view(cte_id, entry, entry.get("name") or cte_id.title(), cutoff))
    return out


def _cte_view(cte_id: str, entry: dict | None, default_name: str, cutoff: datetime) -> dict:
    if not entry or not entry.get("last_seen_at"):
        return {
            "id": cte_id,
            "name": default_name,
            "state": "assumed_online",
            "assumed": True,
            "last_seen_at": None,
            "last_online_at": None,
            "last_offline_at": None,
            "units": [],
            "online_units": 0,
            "offline_units": 0,
        }
    last_seen = _parse_ts(entry["last_seen_at"])
    observed = entry.get("state")
    if last_seen < cutoff:
        state = "assumed_online"
        assumed = True
    else:
        state = observed or "assumed_online"
        assumed = (state == "assumed_online")
    units = [
        {"unidad": int(k), "state": v.get("state"), "since": v.get("since")}
        for k, v in (entry.get("units") or {}).items()
    ]
    units.sort(key=lambda u: u["unidad"])
    return {
        "id": cte_id,
        "name": entry.get("name") or default_name,
        "state": state,
        "assumed": assumed,
        "last_seen_at": entry.get("last_seen_at"),
        "last_online_at": entry.get("last_online_at"),
        "last_offline_at": entry.get("last_offline_at"),
        "last_change_at": entry.get("last_change_at"),
        "units": units,
        "online_units": sum(1 for u in units if u["state"] == "online"),
        "offline_units": sum(1 for u in units if u["state"] == "offline"),
    }


def current_state(events: list[dict], pronostico_recent_h: int = 12) -> dict:
    """Compute live state from the most recent events.

    `events` is the buffer of recent events (typically last 24-48h). We scan
    from newest to oldest, taking the first authoritative signal per block.
    """
    events = sorted(events, key=lambda e: e["id"], reverse=True)
    blocks: dict[int, dict] = {}  # bloque -> {state, since, source_id}
    last_total_mw = None
    last_total_mw_ts = None
    last_actualizacion_blocks: dict[int, dict] = {}
    last_averias = None
    last_daf = None
    last_pronostico = None
    # SEN: latest daf / restablecimiento_daf events in chronological order
    sen_events: list[dict] = []
    partial_sen_events: list[dict] = []
    # CTE: per (cte_id, unidad) the most recent state
    cte_units: dict[tuple[str, int], dict] = {}
    cte_meta: dict[str, str] = {}  # cte_id -> display name

    as_of = events[0]["ts"] if events else None

    for e in events:
        t = e["type"]
        b = e.get("bloque")
        if t == "actualizacion_bloques" and last_total_mw is None:
            last_total_mw = e.get("total_mw")
            last_total_mw_ts = e["ts"]
            for blk in e.get("blocks", []):
                bn = blk["bloque"]
                if bn not in last_actualizacion_blocks:
                    last_actualizacion_blocks[bn] = {**blk, "ts": e["ts"]}
        if t in ("inicio_afectacion", "restablecimiento") and b and b not in blocks:
            blocks[b] = {
                "state": "apagado" if t == "inicio_afectacion" else "encendido",
                "since": e["ts"],
                "emergency": e.get("emergency", False),
            }
        if t == "averias" and last_averias is None:
            last_averias = {"ts": e["ts"], "averias": e.get("averias", [])}
        if t in ("desconexion_total_sen", "restablecimiento_sen"):
            sen_events.append(e)
        if t in ("caida_parcial_sen", "reconexion_parcial_sen"):
            partial_sen_events.append(e)
        if t in ("daf", "restablecimiento_daf") and last_daf is None:
            last_daf = {"ts": e["ts"], "type": t}
        if t == "unidad_termoelectrica":
            cte = e.get("cte_id")
            unit = e.get("unidad")
            state = e.get("state")
            if cte and unit is not None and state and (cte, unit) not in cte_units:
                cte_units[(cte, unit)] = {"state": state, "since": e["ts"]}
                if cte not in cte_meta and e.get("cte_name"):
                    cte_meta[cte] = e["cte_name"]
        if t == "pronostico" and last_pronostico is None:
            cutoff = _parse_ts(as_of) - timedelta(hours=pronostico_recent_h) if as_of else None
            if not cutoff or _parse_ts(e["ts"]) >= cutoff:
                last_pronostico = {"ts": e["ts"]}

    # Build bloques view 1..6.
    # The latest actualizacion_bloques is the source of truth: blocks listed
    # there with minutes_off>0 are apagado; blocks absent from it are encendido.
    # An inicio_afectacion/restablecimiento event overrides only when it is
    # strictly newer than that actualizacion. Without any actualizacion in the
    # buffer we fall back to explicit events alone.
    bloques_view = []
    act_ts = _parse_ts(last_total_mw_ts) if last_total_mw_ts else None
    for bn in range(1, 7):
        b = blocks.get(bn)
        actual = last_actualizacion_blocks.get(bn)
        event_after_act = b and act_ts and _parse_ts(b["since"]) > act_ts

        if act_ts and not event_after_act:
            if actual and (actual["hours_off"] * 60 + actual["minutes_off"]) > 0:
                mins_off = actual["hours_off"] * 60 + actual["minutes_off"]
                since_dt = act_ts - timedelta(minutes=mins_off)
                entry = {
                    "id": bn,
                    "state": "apagado",
                    "since": since_dt.isoformat(),
                    "hours_off_today": actual["hours_off"] + actual["minutes_off"] / 60,
                }
            else:
                entry = {"id": bn, "state": "encendido"}
                if actual:
                    entry["hours_off_today"] = actual["hours_off"] + actual["minutes_off"] / 60
        elif b:
            entry = {"id": bn, "state": b["state"], "since": b["since"]}
            if b["state"] == "apagado" and b.get("emergency"):
                entry["emergency"] = True
        else:
            entry = {"id": bn, "state": "desconocido"}
        bloques_view.append(entry)

    # SEN view — chronological order, infer current state from latest event.
    # Default ONLINE unless an unrecovered collapse is in the recent window.
    sen_events_chrono = sorted(sen_events, key=lambda x: x["id"])
    sen_state = "online"
    sen_since = None
    sen_last_outage_at = None
    sen_last_recovered_at = None
    for ev in sen_events_chrono:
        if ev["type"] == "desconexion_total_sen":
            sen_state = "offline"
            sen_since = ev["ts"]
            sen_last_outage_at = ev["ts"]
        elif ev["type"] == "restablecimiento_sen":
            sen_state = "online"
            sen_since = ev["ts"]
            sen_last_recovered_at = ev["ts"]
    sen_view = {
        "state": sen_state,
        "since": sen_since,
        "last_outage_at": sen_last_outage_at,
        "last_recovered_at": sen_last_recovered_at,
    }

    # Partial SEN state — chronological walk, same pattern as full SEN
    partial_active = False
    partial_since: str | None = None
    partial_last_recovered: str | None = None
    for ev in sorted(partial_sen_events, key=lambda x: x["id"]):
        if ev["type"] == "caida_parcial_sen":
            partial_active = True
            partial_since = ev["ts"]
        elif ev["type"] == "reconexion_parcial_sen":
            partial_active = False
            partial_last_recovered = ev["ts"]
            partial_since = None
    sen_view["partial_sen"] = {
        "active": partial_active,
        "since": partial_since,
        "last_recovered_at": partial_last_recovered,
    }

    # CTE view — aggregate units per plant
    ctes_view: list[dict] = []
    by_plant: dict[str, list[dict]] = {}
    for (cte, unit), info in cte_units.items():
        by_plant.setdefault(cte, []).append({"unidad": unit, **info})
    for cte_id, units in sorted(by_plant.items()):
        units.sort(key=lambda u: u["unidad"])
        online = sum(1 for u in units if u["state"] == "online")
        offline = sum(1 for u in units if u["state"] == "offline")
        if online > 0 and offline == 0:
            plant_state = "online"
        elif offline > 0 and online == 0:
            plant_state = "offline"
        else:
            plant_state = "partial"
        last_change = max(u["since"] for u in units)
        ctes_view.append({
            "id": cte_id,
            "name": cte_meta.get(cte_id, cte_id.title()),
            "state": plant_state,
            "units": units,
            "online_units": online,
            "offline_units": offline,
            "last_change_at": last_change,
        })

    # Averías últimas 24h — aggregate every averías/disparo_circuito event in window
    cutoff = _parse_ts(as_of) - timedelta(hours=24) if as_of else None
    averias_24h: list[dict] = []
    for e in events:
        if cutoff and _parse_ts(e["ts"]) < cutoff:
            continue
        if e["type"] == "averias":
            for a in e.get("averias", []) or []:
                averias_24h.append({"ts": e["ts"], **a})
        elif e["type"] == "disparo_circuito" and e.get("municipio"):
            averias_24h.append({"ts": e["ts"], "municipio": e["municipio"], "kind": "disparo_circuito"})
    averias_24h.sort(key=lambda x: x["ts"], reverse=True)

    return {
        "as_of": as_of,
        "bloques": bloques_view,
        "current_mw_affected": last_total_mw,
        "current_mw_affected_at": last_total_mw_ts,
        "active_averias": last_averias,
        "averias_24h": averias_24h,
        "last_daf": last_daf,
        "last_pronostico": last_pronostico,
        "sen": sen_view,
        "ctes": ctes_view,
    }
