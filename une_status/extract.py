"""Per-type regex field extraction. Pure functions, no I/O."""
from __future__ import annotations

import re

# nota_diaria fields
RE_HORAS_INTERRUMPIDO = re.compile(
    r"se interrumpió el servicio[^.]*?(\d+)\s+horas?\s+y\s+(\d+)\s+minutos?",
    re.IGNORECASE,
)
RE_HORAS_24 = re.compile(r"se interrumpió el servicio[^.]*?las 24 horas", re.IGNORECASE)
RE_MAX_AFECTACION_MW = re.compile(
    r"m[aá]xima afectaci[oó]n fue de\s+(\d+)\s*MW", re.IGNORECASE
)
RE_MAX_AFECTACION_HORA = re.compile(
    r"m[aá]xima afectaci[oó]n fue de\s+\d+\s*MW a las\s+(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)",
    re.IGNORECASE,
)
RE_EMERGENCIA_MW = re.compile(r"EMERGENCIA con\s+(\d+)\s*MW", re.IGNORECASE)
RE_RESTABLECIDO_HORA = re.compile(
    r"restableci[oó] el servicio a la?s?\s+(\d{1,2}:\d{2}\s*(?:AM|PM|am|pm)?)",
    re.IGNORECASE,
)
RE_AL_CIERRE_MW = re.compile(
    r"al cierre[^.]*?\((\d+)\s*MW\)", re.IGNORECASE
)
RE_AL_CIERRE_BLOQUES = re.compile(
    r"al cierre[^.]*?(\d+)\s+bloques?", re.IGNORECASE
)

# actualizacion_bloques: "BLOQUE 4 17 horas y 16 minutos" (sometimes 0 minutos missing)
RE_BLOQUE_ROW = re.compile(
    r"bloque\s+(\d)\s+(\d+)\s+horas?(?:\s+y\s+(\d+)\s+minutos?)?",
    re.IGNORECASE,
)
RE_TOTAL_MW_ACTUAL = re.compile(
    r"se afectan\s+(\d+)\s*MW", re.IGNORECASE
)

# inicio_afectacion / restablecimiento: "bloque no.X"
RE_BLOQUE_NUM = re.compile(r"bloque\s+(?:no\.?\s*|n[°º]\.?\s*)?(\d)", re.IGNORECASE)
RE_EMERGENCIA_KEYWORD = re.compile(r"emergencia", re.IGNORECASE)

# averias
RE_MUNICIPIO = re.compile(r"municipio\s+([A-Za-záéíóúñÁÉÍÓÚÑ\.\s]+?)(?:,|\.)", re.IGNORECASE)
RE_DIRECCION = re.compile(
    r"(?:dirección|direccion|localiza[^,]*en|calzada|calle|avenida|av\.)\s+(.+?)(?:[\.\n]|$)",
    re.IGNORECASE,
)

# unidad_termoelectrica: "🟢 20:15 || En línea la Unidad 4 de la CTE Carlos Manuel de Céspedes."
# Also matches: 'Fuera de línea la Unidad 1 de la CTE Lidio Ramón Pérez "Felton"'
RE_UNIDAD_ESTADO = re.compile(
    r"(en l[íi]nea|fuera de l[íi]nea|sali[oó] de l[íi]nea|sincroniz\w*|dispar[oó]|sali[oó])\s+(?:la\s+)?unidad\s+(?:nro\.?\s*)?(\d+)\s+de\s+la\s+cte\s+(.+?)(?:[\.,;]|\s+por\s+|\s+debido|\s+desde|$)",
    re.IGNORECASE,
)
RE_UNIDAD_TIME = re.compile(r"(\d{1,2}:\d{2})\s*\|\|")


# Canonical CTE registry. Maps raw plant-name fragments (lowercase, accent-stripped)
# to a stable id + display name. Order matters: longer/more-specific aliases first.
CTE_REGISTRY: list[tuple[str, str, str]] = [
    # alias-substring, canonical id, display name
    ("lidio ramon perez", "felton", "Lidio Ramón Pérez (Felton)"),
    ("felton", "felton", "Lidio Ramón Pérez (Felton)"),
    ("antonio guiteras", "guiteras", "Antonio Guiteras"),
    ("guiteras", "guiteras", "Antonio Guiteras"),
    ("maximo gomez", "maximo-gomez", "Máximo Gómez (Mariel)"),
    ("mariel", "maximo-gomez", "Máximo Gómez (Mariel)"),
    ("carlos manuel de cespedes", "cespedes", "Carlos M. de Céspedes (Cienfuegos)"),
    ("cespedes", "cespedes", "Carlos M. de Céspedes (Cienfuegos)"),
    ("cienfuegos", "cespedes", "Carlos M. de Céspedes (Cienfuegos)"),
    ("diez de octubre", "nuevitas", "10 de Octubre (Nuevitas)"),
    ("10 de octubre", "nuevitas", "10 de Octubre (Nuevitas)"),
    ("nuevitas", "nuevitas", "10 de Octubre (Nuevitas)"),
    ("otto parellada", "tallapiedra", "Otto Parellada (Tallapiedra)"),
    ("tallapiedra", "tallapiedra", "Otto Parellada (Tallapiedra)"),
    ("ernesto guevara", "guevara", "Ernesto Guevara (Santa Cruz)"),
    ("santa cruz", "guevara", "Ernesto Guevara (Santa Cruz)"),
    ("renté", "rente", "Antonio Maceo (Renté)"),
    ("rente", "rente", "Antonio Maceo (Renté)"),
    ("antonio maceo", "rente", "Antonio Maceo (Renté)"),
]


def _strip_accents(s: str) -> str:
    repl = str.maketrans("áéíóúüñÁÉÍÓÚÜÑ", "aeiouunAEIOUUN")
    return s.translate(repl)


def normalize_cte(raw: str) -> tuple[str, str] | None:
    """Return (id, display_name) for a raw CTE name fragment, or None."""
    if not raw:
        return None
    key = _strip_accents(raw).lower()
    # strip surrounding quotes/punctuation
    key = re.sub(r'[\"\'“”«»\(\)]', " ", key)
    key = " ".join(key.split())
    for alias, cid, display in CTE_REGISTRY:
        if alias in key:
            return cid, display
    return None


def _parse_clock(s: str) -> str:
    """'11:00 PM' → '23:00'; '08:50 AM' → '08:50'; '20:30' → '20:30'."""
    if not s:
        return ""
    s = s.strip().upper().replace(" ", "")
    m = re.match(r"^(\d{1,2}):(\d{2})(AM|PM)?$", s)
    if not m:
        return ""
    h, mm, ampm = int(m.group(1)), m.group(2), m.group(3)
    if ampm == "PM" and h != 12:
        h += 12
    if ampm == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{mm}"


def extract(msg_type: str, text: str) -> dict:
    """Extract fields for a typed message."""
    t = " ".join((text or "").split())
    out: dict = {}

    if msg_type == "nota_diaria":
        if m := RE_HORAS_INTERRUMPIDO.search(t):
            out["interruption_minutes"] = int(m.group(1)) * 60 + int(m.group(2))
        elif RE_HORAS_24.search(t):
            out["interruption_minutes"] = 24 * 60
        if m := RE_MAX_AFECTACION_MW.search(t):
            out["max_affected_mw"] = int(m.group(1))
        if m := RE_MAX_AFECTACION_HORA.search(t):
            out["max_affected_clock"] = _parse_clock(m.group(1))
        if m := RE_EMERGENCIA_MW.search(t):
            out["emergency_mw"] = int(m.group(1))
        if m := RE_RESTABLECIDO_HORA.search(t):
            out["restored_clock"] = _parse_clock(m.group(1))
        if m := RE_AL_CIERRE_MW.search(t):
            out["closing_affected_mw"] = int(m.group(1))
        if m := RE_AL_CIERRE_BLOQUES.search(t):
            out["closing_affected_blocks"] = int(m.group(1))

    elif msg_type == "actualizacion_bloques":
        blocks = []
        for b, h, mi in RE_BLOQUE_ROW.findall(t):
            blocks.append({
                "bloque": int(b),
                "hours_off": int(h),
                "minutes_off": int(mi) if mi else 0,
            })
        if blocks:
            out["blocks"] = blocks
        if m := RE_TOTAL_MW_ACTUAL.search(t):
            out["total_mw"] = int(m.group(1))

    elif msg_type == "inicio_afectacion":
        if m := RE_BLOQUE_NUM.search(t):
            out["bloque"] = int(m.group(1))
        out["emergency"] = bool(RE_EMERGENCIA_KEYWORD.search(t))

    elif msg_type == "restablecimiento":
        if m := RE_BLOQUE_NUM.search(t):
            out["bloque"] = int(m.group(1))

    elif msg_type == "averias":
        # Two shapes:
        # (a) "Averías existentes" → list of many transformers (📌 sections)
        # (b) "Consumidores del municipio X ... avería en Y" → single averia
        items = []
        if "averías existentes" in t.lower() or "averias existentes" in t.lower():
            parts = re.split(r"📌|🚨|‼️", t)
            for part in parts:
                mun = RE_MUNICIPIO.search(part)
                dirc = RE_DIRECCION.search(part)
                if mun:
                    item = {"municipio": mun.group(1).strip().rstrip(",.").title()}
                    if dirc:
                        item["direccion"] = dirc.group(1).strip()[:200]
                    items.append(item)
        else:
            # single-averia message — match "municipio X" then optional direccion
            mun = re.search(r"municipio\s+([A-Za-záéíóúñÁÉÍÓÚÑ\s\.]+?)(?:[,\.]|\s+(?:se|las|por))", t, re.IGNORECASE)
            if mun:
                item = {"municipio": mun.group(1).strip().rstrip(",.").title()}
                # direccion: text between "en:" or "en " and end-of-sentence
                m2 = re.search(r"\ben:?\s+([^\.]{5,200}?)(?:[\.\n]|$)", t, re.IGNORECASE)
                if m2:
                    item["direccion"] = m2.group(1).strip()
                # severity
                tl = t.lower()
                if "secundaria" in tl:
                    item["severity"] = "secundaria"
                elif "primaria" in tl:
                    item["severity"] = "primaria"
                items.append(item)
        if items:
            out["averias"] = items

    elif msg_type == "disparo_circuito":
        if m := RE_MUNICIPIO.search(t):
            out["municipio"] = m.group(1).strip().rstrip(",.").title()

    elif msg_type == "unidad_termoelectrica":
        if m := RE_UNIDAD_ESTADO.search(t):
            event, unit, plant_raw = m.group(1), m.group(2), m.group(3)
            event_l = event.lower()
            if "en línea" in event_l or "en linea" in event_l or "sincroniz" in event_l:
                state = "online"
            else:
                state = "offline"
            out["unidad"] = int(unit)
            out["planta"] = plant_raw.strip().rstrip(".,;").title()
            out["state"] = state
            if norm := normalize_cte(plant_raw):
                out["cte_id"], out["cte_name"] = norm
        if m := RE_UNIDAD_TIME.search(t):
            out["clock"] = m.group(1)

    return out
