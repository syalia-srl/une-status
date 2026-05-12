"""Regression tests for the classify+extract pipeline against a frozen sample."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from une_status.classify import classify
from une_status.extract import extract
from une_status.parse import to_event

SAMPLE = Path(__file__).parent / "fixtures" / "eelh_sample.jsonl"


def _load_sample() -> list[dict]:
    return [json.loads(l) for l in SAMPLE.read_text().splitlines() if l.strip()]


def test_sample_loads():
    msgs = _load_sample()
    assert len(msgs) > 500, f"sample must be substantial, got {len(msgs)}"


def test_classifier_coverage():
    """Residual `otro` bucket must stay below 20% of text messages."""
    msgs = _load_sample()
    counts: Counter = Counter()
    text_count = 0
    for m in msgs:
        if not m.get("text"):
            counts["photo_only" if m.get("has_photo") else "empty"] += 1
            continue
        text_count += 1
        counts[classify(m["text"])] += 1
    otro_pct = counts.get("otro", 0) * 100 / text_count
    assert otro_pct < 20, f"too much in 'otro': {otro_pct:.1f}%"


def test_actualizacion_bloques_extracts_blocks():
    msgs = _load_sample()
    actualizaciones = [to_event(m) for m in msgs if classify(m["text"]) == "actualizacion_bloques"]
    assert actualizaciones, "expected actualizacion_bloques events"
    with_blocks = [e for e in actualizaciones if e.get("blocks")]
    pct = len(with_blocks) * 100 / len(actualizaciones)
    assert pct > 80, f"only {pct:.0f}% of actualizacion_bloques have blocks parsed"


def test_nota_diaria_extracts_max_mw():
    msgs = _load_sample()
    notas = [to_event(m) for m in msgs if classify(m["text"]) == "nota_diaria"]
    assert notas, "expected nota_diaria events"
    with_max = [e for e in notas if "max_affected_mw" in e]
    assert len(with_max) >= 0.8 * len(notas), "max_affected_mw coverage < 80%"


def test_inicio_afectacion_has_bloque():
    msgs = _load_sample()
    inicios = [to_event(m) for m in msgs if classify(m["text"]) == "inicio_afectacion"]
    if not inicios:
        return  # no inicios in sample
    with_b = [e for e in inicios if e.get("bloque")]
    assert len(with_b) >= 0.7 * len(inicios), "inicio_afectacion bloque coverage < 70%"


def test_classify_known_strings():
    cases = [
        ("EELH | En el día de ayer se interrumpió el servicio eléctrico en La Habana las 24 horas...", "nota_diaria"),
        ("⚡️ Actualización de afectaciones por déficit en la capital. BLOQUE 4 17 horas y 16 minutos", "actualizacion_bloques"),
        ("Por Disparo Automático por Frecuencia (DAF) se afecta el servicio", "daf"),
        ("Restablecido el servicio eléctrico a los clientes afectados por Disparo Automático", "restablecimiento_daf"),
        ("Consumidores del municipio Arroyo Naranjo se detectó una AVERÍA SECUNDARIA POR TRANSFORMADOR DAÑADO", "averias"),
        ("🟢 20:15 || En línea la Unidad 4 de la CTE Carlos Manuel de Céspedes.", "unidad_termoelectrica"),
        ("‼️ 🔔 Informamos a los clientes asociados al Bloque no.5 que a partir de este momento inicia la afectación por déficit", "inicio_afectacion"),
        ("✅ Informamos a los clientes asociados al bloque no.4 ... inicia de forma gradual el restablecimiento del servicio", "restablecimiento"),
    ]
    for text, expected in cases:
        got = classify(text)
        assert got == expected, f"\ntext: {text[:80]}\nexpected: {expected}\ngot: {got}"


def test_bloque_row_extraction():
    text = ("BLOQUE 4 17 horas y 16 minutos BLOQUE 6 14 horas y 51 minutos "
            "BLOQUE 1 14 horas y 30 minutos BLOQUE 2 14 horas y 03 minutos "
            "BLOQUE 5 13 horas y 09 minutos BLOQUE 3 01 horas y 00 minutos")
    fields = extract("actualizacion_bloques", text)
    assert "blocks" in fields
    assert len(fields["blocks"]) == 6
    by_b = {b["bloque"]: b for b in fields["blocks"]}
    assert by_b[4]["hours_off"] == 17 and by_b[4]["minutes_off"] == 16
    assert by_b[3]["hours_off"] == 1 and by_b[3]["minutes_off"] == 0


def test_termoelectrica_state():
    text = "🟢 20:15 || En línea la Unidad 4 de la CTE Carlos Manuel de Céspedes."
    e = to_event({"id": 1, "ts": "2026-05-12T00:15:00Z", "text": text, "has_photo": False})
    assert e["type"] == "unidad_termoelectrica"
    assert e["unidad"] == 4
    assert "Carlos Manuel De Céspedes" in e["planta"] or "Carlos Manuel" in e["planta"]
    assert e["state"] == "online"


def test_nota_diaria_full_parse():
    text = ("EELH | En el día de ayer se interrumpió el servicio eléctrico en La Habana "
            "las 24 horas, la máxima afectación fue de 468 MW a las 11:00 PM. "
            "Fue necesario apagar circuitos por EMERGENCIA con 122 MW. "
            "Al cierre de la NOTA se encuentran afectados 6 bloques y circuitos de emergencia (390 MW)")
    fields = extract("nota_diaria", text)
    assert fields["interruption_minutes"] == 24 * 60
    assert fields["max_affected_mw"] == 468
    assert fields["max_affected_clock"] == "23:00"
    assert fields["emergency_mw"] == 122
    assert fields["closing_affected_mw"] == 390
    assert fields["closing_affected_blocks"] == 6
