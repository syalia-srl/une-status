"""Rule-based message type classifier.

Order matters — first match wins. Keep the heuristics tight and the residual
`otro` bucket small. Empirically (1020-msg recent sample) we land under ~5%
otro with the patterns below.
"""
from __future__ import annotations

import re

# Pre-compiled patterns; tested against the playground sample.
RE_BLOQUE_HORAS = re.compile(r"bloque\s+\d.*?\d+\s*horas?\s+y", re.IGNORECASE)
RE_DAF = re.compile(r"disparo autom[áa]tico|\bDAF\b", re.IGNORECASE)
# Full SEN collapse — explicit national-blackout markers
RE_SEN_COLLAPSE = re.compile(
    r"desconex[ií][oó]n\s+total\s+del\s+(?:sen|sistema)"
    r"|salida\s+total\s+del\s+(?:sen|sistema)"
    r"|colaps[oó]\s+(?:total\s+)?(?:del\s+)?(?:sen|sistema\s+electroenerg)"
    r"|afectaci[oó]n\s+(?:del\s+)?100\s*%"
    r"|100\s*%\s+del\s+pa[ií]s"
    r"|se\s+perdi[oó]\s+(?:todo\s+)?el\s+(?:sen|sistema)"
    r"|se\s+desconect[oó]\s+(?:todo\s+)?el\s+(?:sen|sistema)"
    r"|cero\s+(?:total\s+)?(?:del\s+)?sen"
    r"|apag[oó]n\s+(?:total\s+)?nacional",
    re.IGNORECASE,
)
RE_SEN_RECOVER = re.compile(
    r"recuperaci[oó]n\s+(?:total\s+)?del\s+(?:sen|sistema)"
    r"|restablecimiento\s+(?:total\s+)?del\s+(?:sen|sistema)"
    r"|restablec\w*\s+(?:total\s+)?(?:el\s+)?(?:sen|sistema\s+electroenerg)"
    r"|se\s+recuper[oó]\s+(?:todo\s+)?el\s+(?:sen|sistema)"
    r"|sincronizaci[oó]n\s+(?:total\s+)?del\s+sen",
    re.IGNORECASE,
)
RE_INICIO_BLOQUE = re.compile(
    r"informamos.*?clientes asociados.*?(?:bloque|circuitos?\s+(?:de\s+)?emergen).*?inicia (?:la )?afect",
    re.IGNORECASE | re.DOTALL,
)
RE_AVERIA_REPAIR = re.compile(
    r"con servicio la aver[íi]a"
    r"|reparada la aver[íi]a"
    r"|normalizado el servicio",
    re.IGNORECASE,
)
RE_DISPARO_CIRCUITO = re.compile(
    r"(?:consumidores del municipio|municipio:?)\s.*?(?:disparo del circuito|circuito disparado|disparados? por)",
    re.IGNORECASE | re.DOTALL,
)
RE_DISPARO_CIRCUITO_SIMPLE = re.compile(
    r"\bdisparado el circuito\b",
    re.IGNORECASE,
)
RE_TRABAJOS_OPERATIVOS = re.compile(
    r"por trabajos operativos|por trabajos planificados", re.IGNORECASE,
)
RE_SEN_UPDATE = re.compile(
    r"actualizaci[oó]n del sistema electroenerg[eé]tico nacional", re.IGNORECASE,
)
RE_TRANSFERIDOS_BLOQUE = re.compile(
    r"se han transferido temporalmente al bloque", re.IGNORECASE,
)
RE_PINNED = re.compile(r"pinned\s+«", re.IGNORECASE)
RE_VIA_LIBRE = re.compile(r"v[íi]a libre", re.IGNORECASE)
RE_UNIDAD_TERMO = re.compile(
    r"unidad\s+(?:nro\.?\s*)?\d.*?cte\s+\S",
    re.IGNORECASE | re.DOTALL,
)


def classify(text: str) -> str:
    """Return a short type tag for a raw message text."""
    if not text:
        return "empty"
    t = " ".join(text.split())
    tl = t.lower()

    # Daily summary
    if "eelh |" in tl or "se interrumpió el servicio" in tl or (
        "en el día de ayer" in tl and "afectación" in tl
    ):
        return "nota_diaria"

    # Full-grid collapse signals — these are RARE, must run before DAF check.
    # A DAF is partial; a "desconexión total" / "salida total" / "afectación
    # del 100% del país" is a national blackout (the real "SEN caído").
    if RE_SEN_COLLAPSE.search(tl):
        if RE_SEN_RECOVER.search(tl):
            return "restablecimiento_sen"
        return "desconexion_total_sen"
    if RE_SEN_RECOVER.search(tl):
        return "restablecimiento_sen"

    # DAF restoration vs DAF event (partial frequency event, NOT a SEN collapse)
    if RE_DAF.search(tl):
        if "restablec" in tl:
            return "restablecimiento_daf"
        return "daf"

    # Block updates: "Actualización de afectaciones" or "BLOQUE N X horas"
    if "actualización de afectaciones" in tl or "actualizacion de afectaciones" in tl:
        return "actualizacion_bloques"
    if RE_BLOQUE_HORAS.search(tl):
        return "actualizacion_bloques"

    # Block-level inicio
    if RE_INICIO_BLOQUE.search(tl):
        return "inicio_afectacion"

    # Avería repairs without "restablec" — must precede generic restablecimiento check
    if RE_AVERIA_REPAIR.search(tl):
        return "restablecimiento"

    # Restoration (generic)
    if "restablec" in tl or "recuperación" in tl or "recuperacion" in tl:
        return "restablecimiento"

    # Averías (existentes lists, transformadores dañados, averías primarias/secundarias)
    if (
        "averías existentes" in tl or "averias existentes" in tl
        or "transformador dañado" in tl
        or "avería primaria" in tl or "averia primaria" in tl
        or "avería secundaria" in tl or "averia secundaria" in tl
        or "se detectó una avería" in tl or "se detecto una averia" in tl
        or "avería por" in tl or "averia por" in tl  # gap-3
    ):
        return "averias"

    # Municipio + disparo del circuito (or simpler "disparado el circuito" phrase)
    if RE_DISPARO_CIRCUITO.search(tl) or RE_DISPARO_CIRCUITO_SIMPLE.search(tl):
        return "disparo_circuito"

    # Via libre / fin afectación
    if RE_VIA_LIBRE.search(tl):
        return "via_libre"

    # Termoeléctrica unit on/off
    if RE_UNIDAD_TERMO.search(tl):
        return "unidad_termoelectrica"

    # Pronóstico
    if "pronóstico" in tl or "pronostico" in tl or "se prevé" in tl or "se preve" in tl:
        return "pronostico"

    # Planned trabajos operativos (treated as mantenimiento bucket)
    if RE_TRABAJOS_OPERATIVOS.search(tl) or "mantenimiento" in tl or "planificad" in tl:
        return "mantenimiento"

    # SEN national update embedded in EELH stream
    if RE_SEN_UPDATE.search(tl):
        return "sen_update"

    # Block transfer
    if RE_TRANSFERIDOS_BLOQUE.search(tl):
        return "transferencia_bloque"

    # Pinned summary message
    if RE_PINNED.search(tl):
        return "pinned"

    # Customer service / outreach
    if "líneas de atención" in tl or "comuníquese" in tl or "centro de atención telefónica" in tl:
        return "servicio_cliente"

    if len(t) < 80:
        return "corto"

    return "otro"
