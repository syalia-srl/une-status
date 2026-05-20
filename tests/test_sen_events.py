import pytest
from une_status.classify import classify
from une_status.extract import extract

F1 = (
    "⚡\n"
    "Actualización del Sistema Electroenergético Nacional para el 14 de mayo de 2026.\n"
    "A las 06:09 ocurrió una caída parcial del sistema desde la provincia de Ciego de Ávila "
    "hasta Guantánamo. La disponibilidad del SEN a las 06:30 horas es de 636 MW, la demanda "
    "2420 MW con 1790 MW afectados. En estos momentos se encuentra en proceso de "
    "restablecimiento la zona afectada.\n"
    "Leer más: …"
)

F2 = (
    "🟢\n"
    "Actualización sobre la situación del SEN\n"
    "👉 A las 8:16 se logró enlazar la provincia Ciego de Ávila al SEN.\n"
    "👉 El resto de las provincias se encuentra trabajando con microsistemas.\n"
    "Continuaremos informando."
)

F3 = (
    "🟢\n"
    "Actualización sobre la situación del SEN\n"
    "👉 A las 9:19 se logró enlazar la provincia Camagüey al SEN.\n"
    "👉 Ya tiene servicio la Unidad 6 de la CTE Diez de Octubre, para comenzar el proceso "
    "de arranque.\n"
    "Continuaremos informando."
)

F4 = (
    "⚡\n"
    "Actualización del Sistema Electroenergético Nacional para el 13 de mayo de 2026.\n"
    "Leer más: https://www.unionelectrica.cu/nota-informativa/"
)

F5 = (
    "⚡\n"
    "Actualización del Sistema Electroenergético Nacional.\n"
    "A las 6:15 am se produjo nuevamente la desconexión total del "
    "Sistema Electroenergético Nacional.\n"
    "Se trabaja en el restablecimiento del servicio.\n"
)

# F6 is synthetic — phrased so "se recuperó el SEN" triggers RE_SEN_RECOVER
F6 = (
    "🟢\n"
    "Actualización sobre la situación del SEN.\n"
    "Se recuperó el SEN en un 35% de su capacidad habitual.\n"
    "Continuaremos informando.\n"
)


@pytest.mark.parametrize("text,expected", [
    (F1, "caida_parcial_sen"),
    (F2, "reconexion_parcial_sen"),
    (F3, "reconexion_parcial_sen"),
    (F4, "sen_update"),
    (F5, "desconexion_total_sen"),
    (F6, "restablecimiento_sen"),
])
def test_sen_event_classification(text, expected):
    assert classify(text) == expected


def test_extract_desconexion_total_sen_clock():
    result = extract("desconexion_total_sen", F5)
    assert result.get("clock") == "06:15"


def test_extract_restablecimiento_sen_recovery_pct():
    result = extract("restablecimiento_sen", F6)
    assert result.get("recovery_pct") == 35
