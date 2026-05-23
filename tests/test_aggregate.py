"""Aggregation unit tests."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from une_status.aggregate import (
    _infer_implicit_block_starts,
    current_state,
    daily_rollup,
    havana_date,
    monthly_rollup,
)

_TZ_HAV = ZoneInfo("America/Havana")


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
        {"id": 1, "ts": "2026-05-12T10:00:00+00:00", "type": "desconexion_total_sen"},
        {"id": 2, "ts": "2026-05-12T10:30:00+00:00", "type": "restablecimiento_sen"},
        {"id": 3, "ts": "2026-05-12T11:00:00+00:00", "type": "unidad_termoelectrica",
         "cte_id": "felton", "cte_name": "Felton", "unidad": 1, "state": "offline"},
        {"id": 4, "ts": "2026-05-12T13:00:00+00:00", "type": "unidad_termoelectrica",
         "cte_id": "felton", "cte_name": "Felton", "unidad": 1, "state": "online"},
    ]
    r = daily_rollup("2026-05-12", events, finalized=True)
    assert r["sen_outage"] is True
    assert r["sen_collapse_count"] == 1
    assert r["sen_outage_minutes"] == 30
    assert r["cte_offline_minutes"]["felton"] == 120


def test_daily_rollup_daf_does_not_count_as_sen_outage():
    """DAF is a partial frequency trip — must NOT trigger sen_outage."""
    events = [
        {"id": 1, "ts": "2026-05-12T10:00:00+00:00", "type": "daf"},
        {"id": 2, "ts": "2026-05-12T10:30:00+00:00", "type": "restablecimiento_daf"},
    ]
    r = daily_rollup("2026-05-12", events, finalized=True)
    assert r["sen_outage"] is False
    assert r["sen_collapse_count"] == 0
    assert r["sen_outage_minutes"] == 0
    assert r["daf_count"] == 1


def test_current_state_sen_and_cte():
    events = [
        {"id": 1, "ts": "2026-05-12T10:00:00+00:00", "type": "desconexion_total_sen"},
        {"id": 2, "ts": "2026-05-12T10:30:00+00:00", "type": "restablecimiento_sen"},
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


def test_current_state_daf_does_not_set_sen_offline():
    """A DAF event alone must NOT make the SEN appear offline."""
    events = [
        {"id": 1, "ts": "2026-05-12T10:00:00+00:00", "type": "daf"},
    ]
    cs = current_state(events)
    assert cs["sen"]["state"] == "online"
    assert cs["sen"]["last_outage_at"] is None


def test_daily_rollup_partial_sen_outage_minutes():
    """2 partial collapses + 1 reconnect: second interval is open (counts to midnight).
    Full SEN outage minutes must stay 0 (no desconexion_total_sen events).
    """
    events = [
        {"id": 10, "ts": "2026-05-13T14:00:00+00:00", "type": "caida_parcial_sen"},
        {"id": 11, "ts": "2026-05-13T16:00:00+00:00", "type": "reconexion_parcial_sen"},
        {"id": 12, "ts": "2026-05-13T20:00:00+00:00", "type": "caida_parcial_sen"},
    ]
    r = daily_rollup("2026-05-13", events, finalized=False)
    assert r["partial_sen_outage_minutes"] > 0
    assert r["sen_outage_minutes"] == 0
    assert r["partial_sen_collapse_count"] == 2
    assert r["partial_sen_reconnect_count"] == 1


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


def test_current_state_infers_restoration_from_actualizacion():
    """Block has explicit inicio_afectacion; a later actualizacion_bloques
    shows hours_off=0 for that block → state must be overridden to encendido."""
    events = [
        {
            "id": 10,
            "ts": "2026-05-12T08:00:00+00:00",
            "type": "inicio_afectacion",
            "bloque": 3,
            "emergency": True,
        },
        {
            "id": 20,
            "ts": "2026-05-12T10:00:00+00:00",
            "type": "actualizacion_bloques",
            "total_mw": 400,
            "blocks": [{"bloque": 3, "hours_off": 0, "minutes_off": 0}],
        },
    ]
    cs = current_state(events)
    b3 = next(b for b in cs["bloques"] if b["id"] == 3)
    assert b3["state"] == "encendido"
    assert not b3.get("emergency")


def test_current_state_no_restoration_without_later_actualizacion():
    """Regression guard: block with explicit inicio_afectacion and no
    actualizacion_bloques following must stay apagado."""
    events = [
        {
            "id": 10,
            "ts": "2026-05-12T08:00:00+00:00",
            "type": "inicio_afectacion",
            "bloque": 3,
            "emergency": False,
        },
    ]
    cs = current_state(events)
    b3 = next(b for b in cs["bloques"] if b["id"] == 3)
    assert b3["state"] == "apagado"


def test_current_state_actualizacion_overrides_stale_restablecimiento():
    """Bug 2026-05-19: a B→B transition msg (restab. B2 + inicio B5) only
    captures the restab; the inicio is lost during extraction. A later
    actualizacion_bloques that lists B5 as off must mark it apagado even
    when an older restablecimiento for B5 exists in the buffer.
    """
    events = [
        # earlier in the day: B5 was restored
        {"id": 5, "ts": "2026-05-19T10:00:00+00:00", "type": "restablecimiento", "bloque": 5},
        # later: actualizacion lists B5 as still off — the missed inicio
        # happened between these two, but extraction lost it.
        {
            "id": 20,
            "ts": "2026-05-19T17:12:00+00:00",
            "type": "actualizacion_bloques",
            "total_mw": 500,
            "blocks": [
                {"bloque": 1, "hours_off": 6, "minutes_off": 27},
                {"bloque": 3, "hours_off": 2, "minutes_off": 25},
                {"bloque": 5, "hours_off": 2, "minutes_off": 7},
            ],
        },
    ]
    cs = current_state(events)
    by_id = {b["id"]: b for b in cs["bloques"]}
    assert by_id[5]["state"] == "apagado"
    # since = actualizacion.ts - 2h7m = 15:05Z
    assert by_id[5]["since"] == "2026-05-19T15:05:00+00:00"
    assert by_id[1]["state"] == "apagado"
    assert by_id[1]["since"] == "2026-05-19T10:45:00+00:00"
    assert by_id[3]["state"] == "apagado"
    # blocks not in the latest actualizacion are encendido
    assert by_id[2]["state"] == "encendido"
    assert by_id[4]["state"] == "encendido"
    assert by_id[6]["state"] == "encendido"


def test_current_state_event_after_actualizacion_wins():
    """An inicio_afectacion or restablecimiento whose ts is later than the
    latest actualizacion_bloques must override the actualizacion-derived
    state for that block."""
    events = [
        {
            "id": 10,
            "ts": "2026-05-19T17:12:00+00:00",
            "type": "actualizacion_bloques",
            "total_mw": 300,
            "blocks": [
                {"bloque": 3, "hours_off": 2, "minutes_off": 25},
            ],
        },
        # B4 not in actualizacion, but a later event puts it apagado (emergencia)
        {
            "id": 11,
            "ts": "2026-05-19T17:21:00+00:00",
            "type": "inicio_afectacion",
            "bloque": 4,
            "emergency": True,
        },
        # B3 listed apagado in actualizacion, but a later event restored it
        {
            "id": 12,
            "ts": "2026-05-19T17:30:00+00:00",
            "type": "restablecimiento",
            "bloque": 3,
        },
    ]
    cs = current_state(events)
    by_id = {b["id"]: b for b in cs["bloques"]}
    assert by_id[4]["state"] == "apagado"
    assert by_id[4]["since"] == "2026-05-19T17:21:00+00:00"
    assert by_id[4].get("emergency") is True
    assert by_id[3]["state"] == "encendido"
    assert by_id[3]["since"] == "2026-05-19T17:30:00+00:00"


def test_current_state_restablecimiento_gradual_marks_encendiendose():
    """A restablecimiento_gradual event within the 10-min TTL window must
    surface the bloque as 'encendiendose' (transitional yellow state)."""
    # as_of will be id=20 ts; gradual is 3 min earlier — within 10-min window.
    events = [
        {"id": 10, "ts": "2026-05-19T17:00:00+00:00", "type": "restablecimiento_gradual", "bloque": 5},
        {"id": 20, "ts": "2026-05-19T17:03:00+00:00", "type": "averias", "averias": []},
    ]
    cs = current_state(events)
    b5 = next(b for b in cs["bloques"] if b["id"] == 5)
    assert b5["state"] == "encendiendose"
    assert b5["since"] == "2026-05-19T17:00:00+00:00"


def test_current_state_transicion_bloques_splits_into_two_states():
    """transicion_bloques carries bloque_on + bloque_off: the on side becomes
    encendiendose, the off side becomes apagandose, both with the same since."""
    events = [
        {"id": 10, "ts": "2026-05-19T14:35:00+00:00", "type": "transicion_bloques",
         "bloque_on": 6, "bloque_off": 3},
        {"id": 20, "ts": "2026-05-19T14:38:00+00:00", "type": "averias", "averias": []},
    ]
    cs = current_state(events)
    by_id = {b["id"]: b for b in cs["bloques"]}
    assert by_id[6]["state"] == "encendiendose"
    assert by_id[6]["since"] == "2026-05-19T14:35:00+00:00"
    assert by_id[3]["state"] == "apagandose"
    assert by_id[3]["since"] == "2026-05-19T14:35:00+00:00"


def test_current_state_transition_decays_after_ttl():
    """Past the 10-min TTL, encendiendose decays to encendido and apagandose
    decays to apagado, preserving the original `since` from the event."""
    events = [
        {"id": 10, "ts": "2026-05-19T14:35:00+00:00", "type": "transicion_bloques",
         "bloque_on": 6, "bloque_off": 3},
        # as_of is 25 min later — well past 10-min TTL
        {"id": 20, "ts": "2026-05-19T15:00:00+00:00", "type": "averias", "averias": []},
    ]
    cs = current_state(events)
    by_id = {b["id"]: b for b in cs["bloques"]}
    assert by_id[6]["state"] == "encendido"
    assert by_id[6]["since"] == "2026-05-19T14:35:00+00:00"
    assert by_id[3]["state"] == "apagado"
    assert by_id[3]["since"] == "2026-05-19T14:35:00+00:00"


def test_current_state_actualizacion_overrides_transition():
    """A later actualizacion_bloques takes precedence over an earlier
    transition event, same as for inicio/restablecimiento."""
    events = [
        {"id": 10, "ts": "2026-05-19T14:35:00+00:00", "type": "transicion_bloques",
         "bloque_on": 6, "bloque_off": 3},
        # actualizacion 5 min later still lists B3 as off, B6 absent (= on)
        {
            "id": 20,
            "ts": "2026-05-19T14:40:00+00:00",
            "type": "actualizacion_bloques",
            "total_mw": 400,
            "blocks": [{"bloque": 3, "hours_off": 0, "minutes_off": 30}],
        },
    ]
    cs = current_state(events)
    by_id = {b["id"]: b for b in cs["bloques"]}
    # actualizacion wins: B6 absent → encendido; B3 listed off → apagado
    assert by_id[6]["state"] == "encendido"
    assert by_id[3]["state"] == "apagado"


def test_day_boundary_carry_forward():
    """Block that started off at 23:50 Havana CDT May 19 (UTC 03:50 May 20) must:
    (a) count 10 minutes on May 19 (23:50 → midnight),
    (b) count 30 minutes on May 20 when called with prior_open_blocks={1} (midnight → 00:30).
    Havana observes CDT (UTC-4) in May, not UTC-5.
    """
    events_may19 = [
        {"id": 1, "ts": "2026-05-20T03:50:00+00:00", "type": "inicio_afectacion", "bloque": 1}
    ]
    events_may20 = [
        {"id": 2, "ts": "2026-05-20T04:30:00+00:00", "type": "restablecimiento", "bloque": 1}
    ]
    assert daily_rollup("2026-05-19", events_may19, finalized=True)["block_outage_minutes"]["1"] == 10
    assert daily_rollup("2026-05-20", events_may20, finalized=True, prior_open_blocks={1})["block_outage_minutes"]["1"] == 30


def test_current_state_pre_actualizacion_partial_restoration_ignored():
    """A 'inicia de forma gradual' message classified as restablecimiento
    that predates the latest actualizacion must NOT override an actualizacion
    that still lists the block as off."""
    events = [
        # 17:01 partial/gradual restoration of B1 (classified as restablecimiento)
        {"id": 30, "ts": "2026-05-19T17:01:00+00:00", "type": "restablecimiento", "bloque": 1},
        # 17:12 actualizacion still shows B1 6h27m off
        {
            "id": 31,
            "ts": "2026-05-19T17:12:00+00:00",
            "type": "actualizacion_bloques",
            "total_mw": 400,
            "blocks": [{"bloque": 1, "hours_off": 6, "minutes_off": 27}],
        },
    ]
    cs = current_state(events)
    b1 = next(b for b in cs["bloques"] if b["id"] == 1)
    assert b1["state"] == "apagado"


# ── F7 / F8 fixtures ──────────────────────────────────────────────────────────

# Havana CDT = UTC-4.  actualizacion at 14:00 UTC = 10:00 Havana.
# Block 3 reports 4h (240 min) off; restablecimiento closes the interval in the
# fallback path so that fallback == primary == 240 and max() is a no-op.
_F7_EVENTS = [
    {
        "id": 1,
        "ts": "2026-05-23T14:00:00+00:00",
        "type": "actualizacion_bloques",
        "total_mw": 300,
        "blocks": [{"bloque": 3, "hours_off": 4, "minutes_off": 0}],
    },
    {
        "id": 2,
        "ts": "2026-05-23T14:00:00+00:00",
        "type": "restablecimiento",
        "bloque": 3,
    },
]

# Block 2 is in prior_open_blocks (carry-forward) AND appears in actualizacion.
_F8_EVENTS = [
    {
        "id": 1,
        "ts": "2026-05-23T14:00:00+00:00",
        "type": "actualizacion_bloques",
        "total_mw": 400,
        "blocks": [{"bloque": 2, "hours_off": 6, "minutes_off": 0}],
    },
]


def test_f7_infer_implicit_block_starts():
    """F7: actualizacion reports block 3 as 4h off; no inicio_afectacion.
    Inferred start = actualizacion_ts − 240 min = 06:00 Havana (no cap needed)."""
    result = _infer_implicit_block_starts(_F7_EVENTS, "2026-05-23", prior_open_blocks=None)
    assert 3 in result
    expected = datetime(2026, 5, 23, 6, 0, tzinfo=_TZ_HAV)  # 10:00 Havana − 4h
    assert result[3] == expected


def test_f7_daily_rollup_gives_240():
    """Criterion 5: daily_rollup for F7 scenario produces block 3 = 240 min,
    identical to pre-inference behavior (primary path already gives 240;
    inference brings fallback to 240 so max() is a no-op)."""
    r = daily_rollup("2026-05-23", _F7_EVENTS, finalized=False)
    assert r["block_outage_minutes"]["3"] == 240


def test_f8_carry_forward_skipped_in_implicit_starts():
    """F8: block 2 is in prior_open_blocks AND in actualizacion_bloques.
    _infer_implicit_block_starts must NOT return an inferred start for block 2
    — carry-forward seeding (midnight) takes precedence."""
    result = _infer_implicit_block_starts(_F8_EVENTS, "2026-05-23", prior_open_blocks={2})
    assert 2 not in result
