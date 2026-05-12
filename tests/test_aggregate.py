"""Aggregation unit tests."""
from __future__ import annotations

from une_status.aggregate import (
    current_state,
    daily_rollup,
    havana_date,
    monthly_rollup,
)


def test_havana_date_dst_boundary():
    # 03:00 UTC == 22:00 (previous day) Havana standard time
    assert havana_date("2026-05-12T03:00:00+00:00") == "2026-05-11"
    # 16:00 UTC == 12:00 Havana standard time
    assert havana_date("2026-05-12T16:00:00+00:00") == "2026-05-12"


def test_daily_rollup_from_nota():
    events = [
        {
            "id": 100,
            "ts": "2026-05-12T11:16:12+00:00",
            "type": "nota_diaria",
            "max_affected_mw": 468,
            "max_affected_clock": "23:00",
            "emergency_mw": 122,
            "interruption_minutes": 1440,
        },
        {
            "id": 99,
            "ts": "2026-05-12T10:00:00+00:00",
            "type": "actualizacion_bloques",
            "total_mw": 346,
            "blocks": [
                {"bloque": 1, "hours_off": 14, "minutes_off": 30},
                {"bloque": 2, "hours_off": 14, "minutes_off": 3},
            ],
        },
    ]
    r = daily_rollup("2026-05-12", events, finalized=False)
    assert r["peak_mw_affected"] == 468
    assert r["peak_time"] == "23:00"
    assert r["emergency_mw"] == 122
    assert r["block_outage_minutes"]["1"] == 14 * 60 + 30
    assert r["block_outage_minutes"]["2"] == 14 * 60 + 3


def test_monthly_rollup_aggregates():
    dailies = [
        {
            "date": "2026-04-01", "finalized": True,
            "peak_mw_affected": 300, "interruption_minutes": 600,
            "block_outage_minutes": {"1": 120, "2": 60, "3": 0, "4": 0, "5": 0, "6": 0},
            "emergency_mw": 50, "averias_count_by_municipio": {"Cerro": 2},
            "daf_count": 0,
        },
        {
            "date": "2026-04-02", "finalized": True,
            "peak_mw_affected": 400, "interruption_minutes": 800,
            "block_outage_minutes": {"1": 100, "2": 200, "3": 0, "4": 0, "5": 0, "6": 0},
            "emergency_mw": 30, "averias_count_by_municipio": {"Cerro": 1, "Plaza": 3},
            "daf_count": 1,
        },
    ]
    m = monthly_rollup("2026-04", dailies)
    assert m["dailies_count"] == 2
    assert m["max_peak_mw"] == 400
    assert m["avg_peak_mw"] == 350.0
    assert m["total_interruption_minutes"] == 1400
    assert m["total_block_outage_minutes"]["1"] == 220
    assert m["total_block_outage_minutes"]["2"] == 260
    assert m["averias_count_by_municipio"]["Cerro"] == 3
    assert m["daf_total"] == 1


def test_daily_rollup_sen_outage_and_cte_minutes():
    events = [
        {"id": 1, "ts": "2026-05-12T10:00:00+00:00", "type": "daf"},
        {"id": 2, "ts": "2026-05-12T10:30:00+00:00", "type": "restablecimiento_daf"},
        {"id": 3, "ts": "2026-05-12T11:00:00+00:00", "type": "unidad_termoelectrica",
         "cte_id": "felton", "cte_name": "Felton", "unidad": 1, "state": "offline"},
        {"id": 4, "ts": "2026-05-12T13:00:00+00:00", "type": "unidad_termoelectrica",
         "cte_id": "felton", "cte_name": "Felton", "unidad": 1, "state": "online"},
    ]
    r = daily_rollup("2026-05-12", events, finalized=True)
    assert r["sen_outage"] is True
    assert r["sen_outage_minutes"] == 30
    assert r["daf_count"] == 1
    assert r["cte_offline_minutes"]["felton"] == 120


def test_current_state_sen_and_cte():
    events = [
        {"id": 1, "ts": "2026-05-12T10:00:00+00:00", "type": "daf"},
        {"id": 2, "ts": "2026-05-12T10:30:00+00:00", "type": "restablecimiento_daf"},
        {"id": 3, "ts": "2026-05-12T11:00:00+00:00", "type": "unidad_termoelectrica",
         "cte_id": "guiteras", "cte_name": "Antonio Guiteras", "unidad": 1, "state": "online"},
        {"id": 4, "ts": "2026-05-12T11:00:00+00:00", "type": "unidad_termoelectrica",
         "cte_id": "felton", "cte_name": "Felton", "unidad": 1, "state": "offline"},
    ]
    cs = current_state(events)
    assert cs["sen"]["state"] == "online"
    assert cs["sen"]["last_outage_at"] == "2026-05-12T10:00:00+00:00"
    assert cs["sen"]["last_recovered_at"] == "2026-05-12T10:30:00+00:00"
    by_id = {c["id"]: c for c in cs["ctes"]}
    assert by_id["guiteras"]["state"] == "online"
    assert by_id["felton"]["state"] == "offline"


def test_current_state_picks_latest_per_block():
    events = [
        {"id": 5, "ts": "2026-05-12T12:00:00+00:00", "type": "inicio_afectacion", "bloque": 4, "emergency": False},
        {"id": 6, "ts": "2026-05-12T13:00:00+00:00", "type": "restablecimiento", "bloque": 4},
        {"id": 7, "ts": "2026-05-12T14:00:00+00:00", "type": "inicio_afectacion", "bloque": 3, "emergency": True},
    ]
    cs = current_state(events)
    b3 = next(b for b in cs["bloques"] if b["id"] == 3)
    b4 = next(b for b in cs["bloques"] if b["id"] == 4)
    assert b3["state"] == "apagado"
    assert b3.get("emergency") is True
    assert b4["state"] == "encendido"
