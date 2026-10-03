"""Fallas generales por cliente: Mundial 2026 frente a las mismas fechas históricas.

El fichero SQLite es un índice temporal derivado. No modifica las tres fuentes.
"""

from __future__ import annotations

import csv
from datetime import date, datetime, time, timedelta, timezone
from contextlib import closing, contextmanager
import gzip
from itertools import chain
import json
import math
from pathlib import Path
import re
import sqlite3
import statistics
import zipfile
from zoneinfo import ZoneInfo


ZONA_MX = ZoneInfo("America/Mexico_City")
NIVELES = ("REGION", "SUBREGION", "ENTIDAD_FEDERATIVA", "HUB_CM", "PLAZA")
ARCHIVOS_IR = ("WIDMT_INCIDENCIA_REMEDY", "FECHA_ENVIO")
ARCHIVOS_IRC = (
    "WIDMT_INCIDENCIA_REMEDY_CLIENTE", "WIDMT_INCIDENCIA_REMEDY",
    "WIDMT_CLIENTE", "WIDDIM_REGION", "MAC", "FECHA_INCIDENCIA",
)
TAMANO_LOTE = 10000
INTERVALO_AVANCE = 500000


@contextmanager
def filas_csv(ruta: Path, delimitador: str | None = None):
    """Lee un archivo plano, gzip o ZIP sin descomprimirlo completo a disco."""
    # El valor predeterminado (131072) falla con campos de texto extensos de MT_IR.
    # 2**31-1 también cabe en el tipo C long de Windows.
    csv.field_size_limit(2**31 - 1)
    def lector(texto):
        cabecera = texto.readline()
        if not cabecera:
            raise ValueError(f"{ruta.name}: el archivo está vacío")
        if delimitador is None:
            try:
                separador = csv.Sniffer().sniff(cabecera, delimiters=",|;\t").delimiter
            except csv.Error as exc:
                raise ValueError(f"{ruta.name}: no se reconoció el separador del encabezado CSV") from exc
        else:
            separador = delimitador
        filas = csv.DictReader(chain((cabecera,), texto), delimiter=separador)
        filas.fieldnames = [(campo or "").strip().upper() for campo in filas.fieldnames]
        if len(set(filas.fieldnames)) != len(filas.fieldnames):
            raise ValueError(f"{ruta.name}: el encabezado tiene columnas duplicadas")
        return filas

    if ruta.suffix.lower() == ".zip":
        with zipfile.ZipFile(ruta) as archivo:
            candidatos = [x for x in archivo.namelist() if not x.endswith("/")
                          and not x.startswith("__MACOSX/")
                          and (Path(x).suffix.lower() in (".csv", ".txt")
                               or not Path(x).suffix)]
            if len(candidatos) != 1:
                raise ValueError(f"{ruta.name}: se esperaba exactamente un CSV o TXT en el ZIP")
            import io
            with archivo.open(candidatos[0]) as binario:
                with io.TextIOWrapper(binario, encoding="utf-8-sig", newline="") as texto:
                    yield lector(texto)
    elif ruta.suffix.lower() == ".gz":
        with gzip.open(ruta, "rt", encoding="utf-8-sig", newline="") as texto:
            yield lector(texto)
    else:
        with ruta.open("r", encoding="utf-8-sig", newline="") as texto:
            yield lector(texto)


def campos_requeridos(lector: csv.DictReader, nombres: tuple[str, ...], archivo: Path):
    ausentes = set(nombres) - set(lector.fieldnames or ())
    if ausentes:
        raise ValueError(f"{archivo.name}: faltan columnas {', '.join(sorted(ausentes))}")


def fecha_irc_local(valor: str) -> str:
    """La fecha de MT_IRC procede del timestamp UTC sin conversión del SQL."""
    instant = datetime.fromisoformat(valor)
    instant = instant.replace(tzinfo=timezone.utc) if instant.tzinfo is None else instant.astimezone(timezone.utc)
    return instant.astimezone(ZONA_MX).replace(tzinfo=None).isoformat(sep=" ", timespec="seconds")


def crear_base(con: sqlite3.Connection):
    con.executescript("""
        PRAGMA journal_mode=OFF;
        PRAGMA synchronous=OFF;
        PRAGMA temp_store=FILE;
        PRAGMA cache_size=-65536;
        CREATE TABLE regiones (
            id TEXT PRIMARY KEY,
            REGION TEXT, SUBREGION TEXT, ENTIDAD_FEDERATIVA TEXT,
            HUB_CM TEXT, PLAZA TEXT
        );
        CREATE TABLE incidencias (
            id TEXT PRIMARY KEY, fecha_envio_mx TEXT
        );
        CREATE TABLE afectados (
            id TEXT PRIMARY KEY,
            incidencia TEXT NOT NULL,
            cliente TEXT NOT NULL,
            mac TEXT,
            region_id TEXT NOT NULL,
            fecha_mx TEXT NOT NULL
        );
    """)


def cargar_regiones(con: sqlite3.Connection, ruta: Path) -> int:
    with filas_csv(ruta, "|") as lector:
        campos_requeridos(lector, ("WIDDIM_REGION", *NIVELES), ruta)
        filas = [(r["WIDDIM_REGION"], *(r[k] or "NO IDENTIFICADA" for k in NIVELES)) for r in lector]
    if any(not r[0] for r in filas) or len({r[0] for r in filas}) != len(filas):
        raise ValueError("Dim_Region tiene llaves vacías o repetidas")
    con.executemany("INSERT INTO regiones VALUES (?, ?, ?, ?, ?, ?)", filas)
    con.commit()
    return len(filas)


def descubrir_fuentes_filtradas(carpeta: Path, partes_esperadas: int,
                               anios: list[int]) -> tuple[list[Path], list[Path]]:
    """Selecciona exclusivamente los CSV filtrados, sin acceder a los originales."""
    if partes_esperadas < 1:
        raise ValueError("partes_irc_esperadas debe ser positivo")
    generales, clientes = carpeta / "fallas_generales", carpeta / "fallas_clientes"
    for ruta in (generales, clientes):
        if not ruta.is_dir():
            raise FileNotFoundError(f"Falta la carpeta filtrada: {ruta}")
    ir, partes = {}, {}
    for ruta in generales.iterdir():
        coincidencia = re.fullmatch(r"Dataset_Fallas_Generales_Historia_([0-9]{4})\.csv",
                                   ruta.name, re.IGNORECASE)
        if not ruta.is_file() or not coincidencia:
            continue
        anio = int(coincidencia.group(1))
        if anio in ir:
            raise ValueError(f"MT_IR tiene dos archivos para el año {anio}")
        ir[anio] = ruta
    if set(ir) != set(anios):
        raise ValueError(f"Particiones MT_IR: faltan {sorted(set(anios) - ir.keys())}; "
                         f"años adicionales: {sorted(ir.keys() - set(anios))}")
    for ruta in clientes.iterdir():
        if not ruta.is_file():
            continue
        if not ruta.name.lower().startswith("remedy_fallas_clientes_filtro_"):
            continue
        coincidencia = re.fullmatch(r"remedy_fallas_clientes_filtro_([1-9][0-9]*)\.csv",
                                   ruta.name, re.IGNORECASE)
        if not coincidencia:
            raise ValueError(f"Nombre de fragmento filtrado no válido: {ruta.name}")
        numero = int(coincidencia.group(1))
        if numero in partes:
            raise ValueError(f"MT_IRC tiene dos archivos para el fragmento {numero}")
        partes[numero] = ruta
    esperados = set(range(1, partes_esperadas + 1))
    faltantes = sorted(esperados - partes.keys())
    adicionales = sorted(partes.keys() - esperados)
    if faltantes or adicionales:
        raise ValueError(f"Fragmentos MT_IRC: faltan {faltantes}; fuera de 1..{partes_esperadas}: {adicionales}")
    return [ir[a] for a in sorted(ir)], [partes[i] for i in sorted(partes)]


def periodos_analisis(conf: dict) -> dict[int, tuple[datetime, datetime]]:
    """Mismo mes/día, con fin exclusivo, para el objetivo y cada año histórico."""
    inicio = date.fromisoformat(conf["inicio_analisis"])
    fin = date.fromisoformat(conf["fin_analisis"])
    return {anio: (datetime.combine(inicio.replace(year=anio), time.min),
                   datetime.combine(fin.replace(year=anio) + timedelta(days=1), time.min))
            for anio in [*conf["anios_comparacion"], inicio.year]}


def limites_carga(conf: dict, partidos: list[dict]) -> list[tuple[datetime, datetime]]:
    """Tres intervalos separados; conserva días completos y ventanas de partidos."""
    antes = timedelta(minutes=conf["minutos_antes"])
    despues = timedelta(minutes=conf["minutos_despues"])
    limites = []
    for anio, (inicio, fin) in periodos_analisis(conf).items():
        ventanas = [p["inicio"].replace(year=anio) for p in partidos]
        limites.append((min(inicio, *(x - antes for x in ventanas)),
                        max(fin, *(x + despues for x in ventanas))))
    return limites


def normalizar_limites(limites):
    if limites is None:
        return []
    if isinstance(limites[0], datetime):
        return [limites]
    return limites


def cargar_ir(con: sqlite3.Connection, archivos: list[Path],
              limites: list[tuple[datetime, datetime]] | tuple[datetime, datetime] | None = None) -> dict:
    leidos = seleccionados = fuera = 0
    rangos = normalizar_limites(limites)
    for ruta in archivos:
        particion = re.fullmatch(r"Dataset_Fallas_Generales_Historia_([0-9]{4})\.csv",
                                 ruta.name, re.IGNORECASE)
        with filas_csv(ruta) as lector:
            campos_requeridos(lector, ARCHIVOS_IR, ruta)
            lote = []
            for r in lector:
                leidos += 1
                if leidos % INTERVALO_AVANCE == 0:
                    print(f"MT_IR: {leidos:,} filas examinadas, {seleccionados:,} en periodo", flush=True)
                if not r["WIDMT_INCIDENCIA_REMEDY"]:
                    continue
                if particion and (r["FECHA_ENVIO"] or "")[:4] != particion.group(1):
                    raise ValueError(f"{ruta.name}: FECHA_ENVIO no corresponde al año de la partición")
                if rangos:
                    fecha = r["FECHA_ENVIO"] or ""
                    if len(fecha) < 10 or fecha[4] != "-" or fecha[7] != "-":
                        raise ValueError(f"{ruta.name}: FECHA_ENVIO debe comenzar con AAAA-MM-DD")
                    if not any(a.date().isoformat() <= fecha[:10] <= b.date().isoformat()
                               for a, b in rangos):
                        fuera += 1
                        continue
                lote.append((r["WIDMT_INCIDENCIA_REMEDY"], r["FECHA_ENVIO"]))
                seleccionados += 1
                if len(lote) == TAMANO_LOTE:
                    con.executemany("INSERT OR REPLACE INTO incidencias VALUES (?, ?)", lote)
                    con.commit()
                    lote.clear()
            con.executemany("INSERT OR REPLACE INTO incidencias VALUES (?, ?)", lote)
            con.commit()
        print(f"Leido {ruta.name}: {leidos:,} filas de MT_IR; {seleccionados:,} en periodo", flush=True)
    return {"archivos": [p.name for p in archivos], "filas_leidas": leidos,
            "filas_en_periodo": seleccionados, "filas_fuera_periodo": fuera}


def cargar_irc(con: sqlite3.Connection, archivos: list[Path],
               limites: list[tuple[datetime, datetime]] | tuple[datetime, datetime] | None = None) -> dict:
    leidos = registros = omitidos = fuera = 0
    # Prefiltro de fecha UTC conservador; la comparación definitiva se hace en hora de México.
    rangos = normalizar_limites(limites)
    rangos_utc = [((a.date() - timedelta(days=2)).isoformat(),
                  (b.date() + timedelta(days=2)).isoformat()) for a, b in rangos]
    rangos_mx = [(a.isoformat(sep=" "), b.isoformat(sep=" ")) for a, b in rangos]
    for numero, ruta in enumerate(archivos, 1):
        with filas_csv(ruta) as lector:
            campos_requeridos(lector, ARCHIVOS_IRC, ruta)
            lote = []
            for r in lector:
                leidos += 1
                if leidos % INTERVALO_AVANCE == 0:
                    print(f"MT_IRC: {leidos:,} filas examinadas, {registros:,} en periodo", flush=True)
                if any(not r[c] for c in ARCHIVOS_IRC if c != "MAC"):
                    omitidos += 1
                    continue
                valor_utc = r["FECHA_INCIDENCIA"]
                if rangos_utc and not any(a <= valor_utc[:10] <= b for a, b in rangos_utc):
                    fuera += 1
                    continue
                try:
                    fecha = fecha_irc_local(valor_utc)
                except ValueError as exc:
                    raise ValueError(f"{ruta.name}: FECHA_INCIDENCIA no válida") from exc
                if rangos_mx and not any(a <= fecha < b for a, b in rangos_mx):
                    fuera += 1
                    continue
                lote.append((r["WIDMT_INCIDENCIA_REMEDY_CLIENTE"],
                             r["WIDMT_INCIDENCIA_REMEDY"], r["WIDMT_CLIENTE"],
                             r["MAC"] or None, r["WIDDIM_REGION"], fecha))
                registros += 1
                if len(lote) == TAMANO_LOTE:
                    con.executemany("INSERT OR IGNORE INTO afectados VALUES (?, ?, ?, ?, ?, ?)", lote)
                    con.commit()
                    lote.clear()
            con.executemany("INSERT OR IGNORE INTO afectados VALUES (?, ?, ?, ?, ?, ?)", lote)
            con.commit()
        print(f"MT_IRC {numero}/{len(archivos)}: {ruta.name}; {leidos:,} filas examinadas, "
              f"{registros:,} en periodo", flush=True)
    if not registros:
        raise ValueError("MT_IRC no contiene registros utilizables")
    con.executescript("""
        CREATE INDEX idx_afectados_fecha ON afectados(fecha_mx);
        CREATE INDEX idx_afectados_incidencia ON afectados(incidencia);
    """)
    return {"archivos": [p.name for p in archivos], "filas_leidas": leidos,
            "filas_en_periodo": registros, "filas_fuera_periodo": fuera,
            "filas_incompletas_omitidas": omitidos}


def intervalo_dias(inicio: date, fin: date):
    dia = inicio
    while dia <= fin:
        yield dia
        dia += timedelta(days=1)


def verificar_fuentes(con: sqlite3.Connection, config: dict, cuenta_dim: int, info_ir: dict, info_irc: dict) -> dict:
    dias = {r[0]: r[1] for r in con.execute(
        "SELECT substr(fecha_mx, 1, 10), count(*) FROM afectados GROUP BY 1")}
    dias_ir = {r[0]: r[1] for r in con.execute(
        "SELECT substr(fecha_envio_mx, 1, 10), count(*) FROM incidencias GROUP BY 1")}
    dias_unidos = {r[0]: r[1] for r in con.execute("""SELECT substr(a.fecha_mx, 1, 10), count(*)
        FROM afectados a JOIN incidencias i ON i.id=a.incidencia GROUP BY 1""")}
    cobertura = {}
    for anio, (inicio, fin) in periodos_analisis(config).items():
        esperados = [d.isoformat() for d in intervalo_dias(inicio.date(), (fin-timedelta(days=1)).date())]
        cobertura[str(anio)] = {
            "inicio": inicio.date().isoformat(), "fin": (fin-timedelta(days=1)).date().isoformat(),
            "dias_sin_fallas_clientes": [d for d in esperados if d not in dias],
            "dias_sin_fallas_generales": [d for d in esperados if d not in dias_ir],
            "dias_sin_cruce": [d for d in esperados if d not in dias_unidos]}
    faltantes = sorted({d for c in cobertura.values() for campo in
                        ("dias_sin_fallas_clientes", "dias_sin_fallas_generales", "dias_sin_cruce")
                        for d in c[campo]})
    desvinculados = con.execute("""SELECT count(*) FROM afectados a
        LEFT JOIN regiones d ON a.region_id=d.id WHERE d.id IS NULL""").fetchone()[0]
    unicos = con.execute("SELECT count(DISTINCT incidencia) FROM afectados").fetchone()[0]
    unidos = con.execute("""SELECT count(*) FROM incidencias i
        WHERE EXISTS (SELECT 1 FROM afectados a WHERE a.incidencia=i.id)""").fetchone()[0]
    sin_ir = unicos - unidos
    desfases = con.execute("""SELECT a.fecha_mx,i.fecha_envio_mx FROM incidencias i
        JOIN afectados a ON i.id=a.incidencia GROUP BY i.id LIMIT 500""").fetchall()
    diferencias = []
    for f_irc, f_ir in desfases:
        if f_irc and f_ir:
            diferencias.append(abs((datetime.fromisoformat(f_irc) - datetime.fromisoformat(f_ir)).total_seconds()))
    horas_incoherentes = sum(seg > 60 for seg in diferencias)
    calidad = {
        "dimension_regiones": cuenta_dim, "mt_ir": info_ir, "mt_irc": info_irc,
        "dias_analisis_sin_registros": faltantes,
        "cobertura_por_anio": cobertura,
        "rangos_fechas_mx": [min(dias) if dias else None, max(dias) if dias else None],
        "filas_sin_region_en_catalogo": desvinculados,
        "incidencias_irc_distintas": unicos,
        "incidencias_irc_sin_mt_ir": sin_ir,
        "filas_irc_sin_mt_ir": con.execute("""SELECT count(*) FROM afectados a
            LEFT JOIN incidencias i ON i.id=a.incidencia WHERE i.id IS NULL""").fetchone()[0],
        "muestra_incidencias_comparadas_fechas": len(diferencias),
        "muestra_con_diferencia_fecha_mayor_1_minuto": horas_incoherentes,
        "conteos_diarios": dias,
        "conteos_diarios_fallas_generales": dias_ir,
        "conteos_diarios_con_cruce": dias_unidos,
        "nota_cobertura": "Presencia diaria no garantiza un extracto completo; un día sin filas no se interpreta como cero fallas.",
    }
    if desvinculados:
        raise ValueError(f"Existen {desvinculados} filas de MT_IRC sin WIDDIM_REGION en Dim_Region")
    if diferencias and horas_incoherentes / len(diferencias) > .01:
        raise ValueError("FECHA_INCIDENCIA no coincide con FECHA_ENVIO tras convertir UTC a hora de México")
    return calidad


def leer_partidos(ruta: Path) -> list[dict]:
    with filas_csv(ruta) as lector:
        campos_requeridos(lector, ("PARTIDO_ID", "FECHA_MX", "HORA_INICIO_MX", "PARTIDO"), ruta)
        partidos = []
        vistos = set()
        for fila in lector:
            k = fila["PARTIDO_ID"]
            if k in vistos or not k:
                raise ValueError("Calendario: PARTIDO_ID repetido o vacío")
            vistos.add(k)
            inicio = datetime.combine(date.fromisoformat(fila["FECHA_MX"]),
                                      time.fromisoformat(fila["HORA_INICIO_MX"]))
            partidos.append({**fila, "inicio": inicio})
    if not partidos:
        raise ValueError("El calendario no contiene partidos")
    return partidos


def cuenta_ventana(con: sqlite3.Connection, inicio: datetime, fin: datetime,
                   nivel: str | None) -> dict[str, tuple[int, int, int, int]]:
    if nivel is not None and nivel not in NIVELES:
        raise ValueError(f"Nivel geográfico no soportado: {nivel}")
    expresion = (f"COALESCE(NULLIF(d.{nivel}, ''), 'NO IDENTIFICADA')" if nivel else "'NACIONAL'")
    consulta = f"""SELECT {expresion} AS zona, COUNT(DISTINCT a.cliente),
        COUNT(DISTINCT a.incidencia), COUNT(DISTINCT a.mac),
        COUNT(DISTINCT length(a.cliente) || ':' || a.cliente || a.incidencia)
        FROM afectados a JOIN regiones d ON a.region_id=d.id
        JOIN incidencias i ON a.incidencia=i.id
        WHERE a.fecha_mx >= ? AND a.fecha_mx < ? GROUP BY zona"""
    return {r[0]: tuple(r[1:]) for r in con.execute(
        consulta, (inicio.isoformat(sep=" ", timespec="seconds"),
                   fin.isoformat(sep=" ", timespec="seconds")))}


def cuenta_intervalo_todos(con: sqlite3.Connection, inicio: datetime, fin: datetime,
                           niveles: list[str | None]) -> dict[str | None, dict[str, tuple[int, int, int, int]]]:
    """Selecciona y enlaza una vez; deduplica por separado cada nivel solicitado."""
    niveles = list(dict.fromkeys(niveles))
    for nivel in niveles:
        if nivel is not None and nivel not in NIVELES:
            raise ValueError(f"Nivel geográfico no soportado: {nivel}")
    resultado = {nivel: {} for nivel in niveles}
    if not niveles:
        return resultado

    columnas = "".join(f", d.{nivel}" for nivel in niveles if nivel is not None)
    agregaciones = []
    for nivel in niveles:
        etiqueta = f"'{nivel}'" if nivel is not None else "NULL"
        zona = (f"COALESCE(NULLIF({nivel}, ''), 'NO IDENTIFICADA')"
                if nivel is not None else "'NACIONAL'")
        agregaciones.append(f"""SELECT {etiqueta} AS nivel, {zona} AS zona,
            COUNT(DISTINCT cliente), COUNT(DISTINCT incidencia), COUNT(DISTINCT mac),
            COUNT(DISTINCT falla_cliente) FROM base GROUP BY zona""")
    consulta = f"""WITH base AS MATERIALIZED (
        SELECT a.cliente, a.incidencia, a.mac,
            length(a.cliente) || ':' || a.cliente || a.incidencia AS falla_cliente{columnas}
        FROM afectados a JOIN regiones d ON a.region_id=d.id
        JOIN incidencias i ON a.incidencia=i.id
        WHERE a.fecha_mx >= ? AND a.fecha_mx < ?
    ) {" UNION ALL ".join(agregaciones)}"""
    for nivel, zona, *conteos in con.execute(
            consulta, (inicio.isoformat(sep=" ", timespec="seconds"),
                       fin.isoformat(sep=" ", timespec="seconds"))):
        resultado[nivel][zona] = tuple(conteos)
    return resultado


def ventana_cubierta(inicio: datetime, fin: datetime, dias_presentes: set[str]) -> bool:
    return all(d.isoformat() in dias_presentes for d in
               intervalo_dias(inicio.date(), (fin-timedelta(microseconds=1)).date()))


def fechas_comparables(inicio_partido: datetime, anios: list[int]) -> list[datetime]:
    """Misma fecha y hora local; no desplaza la comparación al mismo día semanal."""
    return [inicio_partido.replace(year=anio) for anio in anios]


def cuantilar_95(datos: list[float]) -> float:
    valores = sorted(datos)
    pos = .95 * (len(valores) - 1)
    inferior = math.floor(pos)
    return valores[inferior] + (valores[math.ceil(pos)] - valores[inferior]) * (pos - inferior)


def distancia_euclidea(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def evaluar(actual: tuple[int, int, int], controles: list[tuple[int, int, int]],
            conf: dict) -> dict:
    """KNN por distancia a ventanas normales; la comparación no usa etiquetas."""
    clientes = [x[0] for x in controles]
    n = len(controles)
    k = int(conf.get("k_vecinos_distancia", 3))
    resultado = {"MEDIANA_REFERENCIA": statistics.median(clientes) if n else "",
                 "P95_REFERENCIA": round(cuantilar_95(clientes), 2) if n else "",
                 "EXCESO_CLIENTES": (actual[0] - statistics.median(clientes)) if n else "",
                 "DISTANCIA_VECINOS": "", "P95_DISTANCIA_REFERENCIA": "",
                 "PUNTUACION_DISTANCIA": "", "K_VECINOS": k,
                 "N_REFERENCIAS": n, "ESTADO": "SIN_BASE"}
    if n < max(2, int(conf["minimo_ventanas_comparables"])):
        return resultado

    # Cada magnitud se escala con controles de la misma zona y horario.
    # El término sqrt estabiliza la escala si todos los controles son iguales.
    centros = [statistics.median(x[j] for x in controles) for j in range(3)]
    escalas = []
    for j, centro in enumerate(centros):
        mad = statistics.median(abs(x[j] - centro) for x in controles)
        escalas.append(max(1.0, 1.4826 * mad, math.sqrt(centro + 1)))
    def normalizar(vector):
        return tuple((vector[j] - centros[j]) / escalas[j] for j in range(3))

    normalizados = [normalizar(x) for x in controles]
    objetivo = normalizar(actual)
    distancia_actual = statistics.mean(sorted(distancia_euclidea(objetivo, x)
                                               for x in normalizados)[:k])
    # Distancia de cada control a sus vecinos, excluyéndose a sí mismo.
    distancias_base = [statistics.mean(sorted(distancia_euclidea(x, y)
                                           for j, y in enumerate(normalizados) if j != i)[:k])
                       for i, x in enumerate(normalizados)]
    centro_dist = statistics.median(distancias_base)
    mad_dist = statistics.median(abs(x - centro_dist) for x in distancias_base)
    punt = (distancia_actual - centro_dist) / max(1.0, 1.4826 * mad_dist)
    anomalia = (actual[0] >= int(conf["minimo_clientes_anomalia"])
                and resultado["EXCESO_CLIENTES"] >= int(conf["minimo_exceso_clientes"])
                and actual[0] > resultado["P95_REFERENCIA"]
                and distancia_actual > cuantilar_95(distancias_base)
                and punt >= float(conf.get("minimo_puntuacion_distancia", 3.0)))
    resultado.update({"DISTANCIA_VECINOS": round(distancia_actual, 3),
                      "P95_DISTANCIA_REFERENCIA": round(cuantilar_95(distancias_base), 3),
                      "PUNTUACION_DISTANCIA": round(punt, 2),
                      "ESTADO": "ANOMALIA" if anomalia else "ESPERADO"})
    return resultado


def escribir_csv(ruta: Path, filas: list[dict], campos: list[str]):
    with ruta.open("w", encoding="utf-8-sig", newline="") as fichero:
        escritor = csv.DictWriter(fichero, fieldnames=campos, extrasaction="ignore")
        escritor.writeheader()
        escritor.writerows(filas)


def exportar_detalle_alertas(con: sqlite3.Connection, partidos: list[dict],
                            alertas: list[dict], salida: Path,
                            antes: int, despues: int) -> int:
    """Conserva los identificadores de cliente, MAC e incidencia de cada alerta."""
    ruta = salida / "detalle_clientes_alertados.csv"
    campos = ["PARTIDO_ID", "INICIO_MX", "FECHA_AFECTACION_MX",
              "WIDMT_INCIDENCIA_REMEDY_CLIENTE", "WIDMT_INCIDENCIA_REMEDY",
              "WIDMT_CLIENTE", "MAC", "WIDDIM_REGION", "ENTIDAD_FEDERATIVA",
              "HUB_CM", "PLAZA", "ALERTAS_APLICABLES"]
    por_partido = {}
    for alerta in alertas:
        por_partido.setdefault(alerta["PARTIDO_ID"], set()).add(
            (alerta["NIVEL"], alerta["ZONA"]))
    escritos = 0
    with ruta.open("w", encoding="utf-8-sig", newline="") as fichero:
        escritor = csv.DictWriter(fichero, fieldnames=campos)
        escritor.writeheader()
        for partido in partidos:
            zonas = por_partido.get(partido["PARTIDO_ID"])
            if not zonas:
                continue
            inicio = partido["inicio"]
            a = (inicio - timedelta(minutes=antes)).isoformat(sep=" ", timespec="seconds")
            b = (inicio + timedelta(minutes=despues)).isoformat(sep=" ", timespec="seconds")
            consulta = """SELECT a.fecha_mx, a.id, a.incidencia, a.cliente, a.mac,
                    a.region_id, d.ENTIDAD_FEDERATIVA, d.HUB_CM, d.PLAZA
                FROM afectados a JOIN regiones d ON a.region_id=d.id
                JOIN incidencias i ON a.incidencia=i.id
                WHERE a.fecha_mx >= ? AND a.fecha_mx < ?"""
            for fecha, id_fila, incidencia, cliente, mac, region, entidad, hub, plaza in con.execute(consulta, (a, b)):
                ubicacion = {"NACIONAL": "NACIONAL", "ENTIDAD_FEDERATIVA": entidad,
                             "HUB_CM": hub, "PLAZA": plaza}
                aplicables = sorted(f"{nivel}:{zona}" for nivel, zona in zonas
                                   if ubicacion.get(nivel) == zona)
                if not aplicables:
                    continue
                escritor.writerow({"PARTIDO_ID": partido["PARTIDO_ID"],
                    "INICIO_MX": inicio.isoformat(sep=" "), "FECHA_AFECTACION_MX": fecha,
                    "WIDMT_INCIDENCIA_REMEDY_CLIENTE": id_fila,
                    "WIDMT_INCIDENCIA_REMEDY": incidencia, "WIDMT_CLIENTE": cliente,
                    "MAC": mac or "", "WIDDIM_REGION": region,
                    "ENTIDAD_FEDERATIVA": entidad, "HUB_CM": hub, "PLAZA": plaza,
                    "ALERTAS_APLICABLES": " | ".join(aplicables)})
                escritos += 1
    return escritos


METRICAS = ("CLIENTES_DISTINTOS", "INCIDENCIAS_DISTINTAS", "MAC_DISTINTAS", "FALLAS_CLIENTE")
CERO = (0, 0, 0, 0)


def comparar_metricas(actual, historicos: dict[int, tuple | None]) -> dict:
    """No confunde falta de cobertura con cero, ni divide entre cero."""
    resultado = dict(zip(METRICAS, actual if actual is not None else ("",)*4))
    resultado["FALLAS_PROMEDIO_POR_CLIENTE"] = (
        round(actual[3] / actual[0], 4) if actual and actual[0] else "")
    for anio, valores in historicos.items():
        for j, metrica in enumerate(METRICAS):
            base = valores[j] if valores is not None else None
            valor = actual[j] if actual is not None else None
            resultado[f"{metrica}_{anio}"] = base if base is not None else ""
            resultado[f"DIF_{metrica}_VS_{anio}"] = valor-base if valor is not None and base is not None else ""
            resultado[f"VAR_{metrica}_PCT_VS_{anio}"] = (
                round(100*(valor-base)/base, 2) if valor is not None and base else "")
        resultado[f"FALLAS_PROMEDIO_POR_CLIENTE_{anio}"] = (
            round(valores[3]/valores[0], 4) if valores and valores[0] else "")
    for j, metrica in enumerate(METRICAS):
        completo = all(x is not None for x in historicos.values())
        base = statistics.mean(x[j] for x in historicos.values()) if completo else None
        valor = actual[j] if actual is not None else None
        resultado[f"PROMEDIO_HISTORICO_{metrica}"] = base if base is not None else ""
        resultado[f"DIF_{metrica}_VS_HISTORICO"] = valor-base if valor is not None and base is not None else ""
        resultado[f"VAR_{metrica}_PCT_VS_HISTORICO"] = (
            round(100*(valor-base)/base, 2) if valor is not None and base else "")
    resultado["ANIOS_HISTORICOS_DISPONIBLES"] = "|".join(str(a) for a, v in historicos.items() if v is not None)
    return resultado


def comparar_intervalos(con, intervalos, anio_objetivo, niveles, dias_presentes):
    """Recuenta clientes distintos para cada intervalo; nunca suma conteos diarios."""
    niveles = list(niveles)
    cubiertos = {a: ventana_cubierta(*v, dias_presentes) for a, v in intervalos.items()}
    todos = {a: cuenta_intervalo_todos(con, *v, niveles) if cubiertos[a] else {}
             for a, v in intervalos.items()}
    for nivel in niveles:
        conteos = {a: resultados.get(nivel, {}) for a, resultados in todos.items()}
        zonas = set().union(*(set(x) for x in conteos.values()))
        if nivel is None:
            zonas.add("NACIONAL")
        for zona in sorted(zonas):
            valores = {a: c.get(zona, CERO) if cubiertos[a] else None for a, c in conteos.items()}
            actual = valores.pop(anio_objetivo)
            yield {"NIVEL": nivel or "NACIONAL", "ZONA": zona,
                   "COBERTURA_COMPLETA": all(cubiertos.values()),
                   **comparar_metricas(actual, valores)}


def exportar_comparacion_periodos(con, conf, salida, dias_presentes):
    periodos = periodos_analisis(conf)
    inicio = date.fromisoformat(conf["inicio_analisis"])
    fin = date.fromisoformat(conf["fin_analisis"])
    objetivo = inicio.year
    total_dias = (fin-inicio).days + 1
    niveles = [None, *conf["niveles_geograficos"]]
    totales = list(comparar_intervalos(con, periodos, objetivo, niveles, dias_presentes))
    for fila in totales:
        fila.update(INICIO_MX=conf["inicio_analisis"], FIN_MX=conf["fin_analisis"])
    escribir_csv(salida / "comparacion_periodo_zona.csv", totales, list(totales[0]))
    print(f"Periodo completo comparado. Iniciando comparación diaria ({total_dias} días)...",
          flush=True)
    diarias = []
    for dia in intervalo_dias(inicio, fin):
        intervalos = {a: (datetime.combine(dia.replace(year=a), time.min),
                          datetime.combine(dia.replace(year=a)+timedelta(days=1), time.min))
                      for a in periodos}
        diarias.extend({"FECHA_MX": dia.isoformat(), **fila} for fila in
                       comparar_intervalos(con, intervalos, objetivo, niveles, dias_presentes))
    escribir_csv(salida / "comparacion_diaria_zona.csv", diarias, list(diarias[0]))
    print(f"Días comparados: {total_dias}/{total_dias}", flush=True)
    return len(totales), len(diarias)


def exportar_fallas_por_cliente(con, conf, salida, dias_presentes):
    """Una fila por cliente, con incidencias distintas de cada año, sin duplicar MAC."""
    periodos = periodos_analisis(conf)
    objetivo = date.fromisoformat(conf["inicio_analisis"]).year
    anios = sorted(periodos)
    con.execute("CREATE TEMP TABLE periodos (anio INTEGER, inicio TEXT, fin TEXT)")
    con.executemany("INSERT INTO periodos VALUES (?, ?, ?)",
                    [(a, i.isoformat(sep=" "), f.isoformat(sep=" ")) for a, (i, f) in periodos.items()])
    columnas = ", ".join(f"COALESCE(MAX(CASE WHEN anio={a} THEN fallas END), 0)" for a in anios)
    consulta = f"""WITH conteos AS (
        SELECT a.cliente, p.anio, COUNT(DISTINCT a.incidencia) AS fallas
        FROM afectados a JOIN incidencias i ON i.id=a.incidencia
        JOIN periodos p ON a.fecha_mx >= p.inicio AND a.fecha_mx < p.fin
        GROUP BY a.cliente, p.anio)
        SELECT cliente, {columnas} FROM conteos GROUP BY cliente ORDER BY cliente"""
    cobertura = {a: ventana_cubierta(*v, dias_presentes) for a, v in periodos.items()}
    campos = ["WIDMT_CLIENTE", *(f"FALLAS_{a}" for a in anios),
              *(campo for a in conf["anios_comparacion"] for campo in
                (f"DIF_FALLAS_VS_{a}", f"VAR_FALLAS_PCT_VS_{a}")), "PROMEDIO_HISTORICO_FALLAS",
              "DIF_FALLAS_VS_HISTORICO", "VAR_FALLAS_PCT_VS_HISTORICO", "COBERTURA_COMPLETA"]
    escritos = 0
    with (salida / "fallas_generales_por_cliente.csv").open("w", encoding="utf-8-sig", newline="") as fichero:
        escritor = csv.DictWriter(fichero, fieldnames=campos)
        escritor.writeheader()
        for cliente, *cuentas in con.execute(consulta):
            valores = dict(zip(anios, cuentas))
            base = statistics.mean(valores[a] for a in conf["anios_comparacion"]) if all(
                cobertura[a] for a in conf["anios_comparacion"]) else None
            actual = valores[objetivo] if cobertura[objetivo] else None
            diferencias = {}
            for a in conf["anios_comparacion"]:
                referencia = valores[a] if cobertura[a] else None
                diferencias[f"DIF_FALLAS_VS_{a}"] = (
                    actual-referencia if actual is not None and referencia is not None else "")
                diferencias[f"VAR_FALLAS_PCT_VS_{a}"] = (
                    round(100*(actual-referencia)/referencia, 2) if actual is not None and referencia else "")
            escritor.writerow({"WIDMT_CLIENTE": cliente,
                **{f"FALLAS_{a}": valores[a] if cobertura[a] else "" for a in anios},
                **diferencias,
                "PROMEDIO_HISTORICO_FALLAS": base if base is not None else "",
                "DIF_FALLAS_VS_HISTORICO": actual-base if actual is not None and base is not None else "",
                "VAR_FALLAS_PCT_VS_HISTORICO": round(100*(actual-base)/base, 2) if actual is not None and base else "",
                "COBERTURA_COMPLETA": all(cobertura.values())})
            escritos += 1
    con.execute("DROP TABLE periodos")
    return escritos


def analizar(con: sqlite3.Connection, conf: dict, partidos: list[dict],
            salida: Path, dias_presentes: set[str]) -> dict:
    niveles = [None, *conf["niveles_geograficos"]]
    antes, despues = conf["minutos_antes"], conf["minutos_despues"]
    cache: dict[tuple, dict] = {}
    cache_evaluaciones: dict[datetime, list[dict]] = {}

    def obtener(inicio: datetime, fin: datetime):
        k = (inicio, fin)
        if k not in cache:
            cache[k] = cuenta_intervalo_todos(con, inicio, fin, niveles)
        return cache[k]

    def evaluar_horario(inicio: datetime):
        """Reutiliza comparaciones y evaluaciones sin datos propios de cada partido."""
        if inicio in cache_evaluaciones:
            return cache_evaluaciones[inicio]
        resultados_horario = []
        control_fechas = fechas_comparables(inicio, conf["anios_comparacion"])
        cobertura_actual = ventana_cubierta(inicio-timedelta(minutes=antes),
                                             inicio+timedelta(minutes=despues), dias_presentes)
        cubiertos = {x.year: ventana_cubierta(x-timedelta(minutes=antes),
                       x+timedelta(minutes=despues), dias_presentes) for x in control_fechas}
        real_todos = obtener(inicio-timedelta(minutes=antes),
                             inicio+timedelta(minutes=despues)) if cobertura_actual else {}
        base_todos = {x.year: obtener(x-timedelta(minutes=antes), x+timedelta(minutes=despues))
                      if cubiertos[x.year] else {} for x in control_fechas}
        for nivel in niveles:
            real = real_todos.get(nivel, {})
            base = {a: resultados.get(nivel, {}) for a, resultados in base_todos.items()}
            zonas = set(real).union(*(set(x) for x in base.values()))
            if nivel is None:
                zonas.add("NACIONAL")
            for zona in zonas:
                actual = real.get(zona, CERO) if cobertura_actual else None
                historicos = {a: x.get(zona, CERO) if cubiertos[a] else None for a, x in base.items()}
                evaluacion = evaluar((actual or CERO)[:3],
                                     [x[:3] for x in historicos.values() if x is not None], conf)
                if not cobertura_actual:
                    evaluacion["ESTADO"] = "SIN_COBERTURA"
                    evaluacion["EXCESO_CLIENTES"] = ""
                resultados_horario.append({"NIVEL": nivel or "NACIONAL", "ZONA": zona,
                    "COBERTURA_COMPLETA": cobertura_actual and all(cubiertos.values()),
                    **comparar_metricas(actual, historicos), **evaluacion})
        cache_evaluaciones[inicio] = resultados_horario
        return resultados_horario

    filas = []
    fallas_sin_base = 0
    for i, partido in enumerate(partidos, 1):
        inicio = partido["inicio"]
        for resultado in evaluar_horario(inicio):
            filas.append({"PARTIDO_ID": partido["PARTIDO_ID"], "PARTIDO": partido["PARTIDO"],
                          "INICIO_MX": inicio.isoformat(sep=" "),
                          "JUEGA_MEXICO": partido.get("JUEGA_MEXICO", ""),
                          "SEDE_EN_MEXICO": partido.get("SEDE_EN_MEXICO", ""),
                          "SEDE": partido.get("SEDE", ""), **resultado})
            fallas_sin_base += resultado["ESTADO"] in ("SIN_BASE", "SIN_COBERTURA")
        if i % 20 == 0 or i == len(partidos):
            print(f"Partidos analizados: {i}/{len(partidos)}", flush=True)
    campos = list(filas[0])
    filas.sort(key=lambda x:(int(x["PARTIDO_ID"]), x["NIVEL"], x["ZONA"]))
    escribir_csv(salida / "anomalias_por_partido_zona.csv", filas, campos)
    escribir_csv(salida / "comparacion_por_partido_zona.csv", filas, campos)
    alertas = [r for r in filas if r["ESTADO"] == "ANOMALIA"]
    alertas.sort(key=lambda x:float(x["EXCESO_CLIENTES"]), reverse=True)
    escribir_csv(salida / "alertas_ordenadas.csv", alertas, campos)
    detalle = exportar_detalle_alertas(con, partidos, alertas, salida, antes, despues)
    print("Comparando días y periodo completo con el histórico...", flush=True)
    totales, diarias = exportar_comparacion_periodos(con, conf, salida, dias_presentes)
    print("Exportando fallas generales por cliente...", flush=True)
    clientes = exportar_fallas_por_cliente(con, conf, salida, dias_presentes)
    return {"partidos": len(partidos), "filas_metricas": len(filas),
            "alertas": len(alertas), "filas_sin_base": fallas_sin_base,
            "filas_detalle_alertas": detalle,
            "filas_comparacion_periodo": totales, "filas_comparacion_diaria": diarias,
            "clientes_comparados": clientes,
            "anios_comparacion": conf["anios_comparacion"],
            "inicio_analisis": conf["inicio_analisis"], "fin_analisis": conf["fin_analisis"],
            "comparacion": "Mismo mes, día y hora local en cada año; promedio de los años históricos",
            "definicion_falla_cliente": "Par distinto (WIDMT_CLIENTE, WIDMT_INCIDENCIA_REMEDY), enlazado con fallas generales",
            "minimo_ventanas_comparables": int(conf["minimo_ventanas_comparables"]),
            "nota_base": "Cada año aporta una referencia por partido; SIN_BASE indica que no alcanza el mínimo para evaluar KNN.",
            "algoritmo": "Detección de anomalías por distancia (k vecinos más cercanos)",
            "variables_modelo": ["CLIENTES_DISTINTOS", "INCIDENCIAS_DISTINTAS", "MAC_DISTINTAS"],
            "k_vecinos": int(conf.get("k_vecinos_distancia", 3)),
            "definicion_ventana": f"desde {antes} min antes hasta {despues} min después del inicio",
            "nota": "Partidos superpuestos comparten observaciones; no sumar sus resultados."}


def ejecutar(ruta_config: Path) -> dict:
    raiz = ruta_config.resolve().parent
    conf = json.loads(ruta_config.read_text(encoding="utf-8"))
    if conf.get("modo_fuentes", "filtrado") != "filtrado":
        raise ValueError("Este análisis solo admite modo_fuentes='filtrado'; no se leerán fuentes originales")
    inicio, fin = date.fromisoformat(conf["inicio_analisis"]), date.fromisoformat(conf["fin_analisis"])
    if inicio > fin or inicio.year != fin.year:
        raise ValueError("El periodo de análisis debe estar ordenado y dentro del mismo año")
    anios = conf.get("anios_comparacion", [])
    if not anios or any(type(a) is not int or a >= inicio.year for a in anios) or len(set(anios)) != len(anios):
        raise ValueError("anios_comparacion debe contener años históricos distintos y anteriores al objetivo")
    if conf["minutos_antes"] < 0 or conf["minutos_despues"] <= 0:
        raise ValueError("La ventana requiere minutos_antes >= 0 y minutos_despues > 0")
    salida = raiz / conf["carpeta_resultados"]
    datos = raiz / conf["carpeta_datos"]
    if conf.get("descargar_datos", False):
        from .descarga import preparar_datos
        preparar_datos(ruta_config)
    fuente_ir, fuente_irc = descubrir_fuentes_filtradas(
        datos, int(conf.get("partes_irc_esperadas", 64)), [*anios, inicio.year])
    partidos = leer_partidos(raiz / conf["calendario"])
    if any(not inicio <= p["inicio"].date() <= fin for p in partidos):
        raise ValueError("El calendario contiene partidos fuera del periodo de análisis")
    limites = limites_carga(conf, partidos)
    k = int(conf.get("k_vecinos_distancia", 3))
    if k < 1 or int(conf["minimo_ventanas_comparables"]) <= k:
        raise ValueError("k_vecinos_distancia debe ser positivo y menor que minimo_ventanas_comparables")
    if conf.get("partidos_esperados") and len(partidos) != conf["partidos_esperados"]:
        raise ValueError(f"Calendario incompleto: se esperaban {conf['partidos_esperados']} partidos")
    for nivel in conf["niveles_geograficos"]:
        if nivel not in NIVELES:
            raise ValueError(f"Nivel no soportado: {nivel}")
    salida.mkdir(parents=True, exist_ok=True)
    trabajo = salida / "_indice_temporal.sqlite"
    if trabajo.exists():
        trabajo.unlink()  # Solo se reemplaza el índice temporal derivado.
    with closing(sqlite3.connect(trabajo)) as con:
        crear_base(con)
        cuenta_dim = cargar_regiones(con, raiz / conf["dimension_region"])
        info_ir = cargar_ir(con, fuente_ir, limites)
        info_irc = cargar_irc(con, fuente_irc, limites)
        calidad = verificar_fuentes(con, conf, cuenta_dim, info_ir, info_irc)
        (salida / "control_calidad.json").write_text(
            json.dumps(calidad, ensure_ascii=False, indent=2), encoding="utf-8")
        if conf["exigir_dias_completos"] and calidad["dias_analisis_sin_registros"]:
            raise ValueError("Faltan días con datos o cruce en 2026 o en el histórico; consulta control_calidad.json")
        dias_presentes = set(calidad["conteos_diarios_con_cruce"]) & set(calidad["conteos_diarios_fallas_generales"])
        resultado = analizar(con, conf, partidos, salida, dias_presentes)
    (salida / "resumen_ejecucion.json").write_text(
        json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Listo: {resultado['clientes_comparados']:,} clientes comparados; "
          f"{resultado['alertas']} alertas en {salida}")
    return resultado
