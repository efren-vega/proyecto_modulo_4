"""Descarga reproducible de los CSV públicos de Google Drive con gdown."""

from __future__ import annotations

import csv
from datetime import date
import json
from pathlib import Path


# Drive puede rechazar el navegador Chrome 39 que gdown anuncia por defecto.
# Identificamos el programa sin usar credenciales ni simular ese navegador.
AGENTE_DESCARGA = "proyecto-mundial-anomalias/1.0"


ENCABEZADOS = {
    "region_y_calendario": {
        "Dataset_Dim_Region.csv": (
            "WIDDIM_REGION", "REGION", "SUBREGION", "ENTIDAD_FEDERATIVA", "HUB_CM", "PLAZA"),
        "calendario_partidos_2026.csv": (
            "PARTIDO_ID", "FECHA_MX", "HORA_INICIO_MX", "PARTIDO"),
    },
    "fallas_generales": ("WIDMT_INCIDENCIA_REMEDY", "FECHA_ENVIO"),
    "fallas_clientes": (
        "WIDMT_INCIDENCIA_REMEDY_CLIENTE", "WIDMT_INCIDENCIA_REMEDY",
        "WIDMT_CLIENTE", "WIDDIM_REGION", "MAC", "FECHA_INCIDENCIA"),
}


def archivos_esperados(conf: dict) -> dict[str, dict[str, tuple[str, ...]]]:
    anios = sorted([*conf["anios_comparacion"], date.fromisoformat(conf["inicio_analisis"]).year])
    partes = int(conf.get("partes_irc_esperadas", 64))
    if partes < 1:
        raise ValueError("partes_irc_esperadas debe ser positivo")
    return {
        "region_y_calendario": ENCABEZADOS["region_y_calendario"],
        "fallas_generales": {
            f"Dataset_Fallas_Generales_Historia_{a}.csv": ENCABEZADOS["fallas_generales"]
            for a in anios},
        "fallas_clientes": {
            f"remedy_fallas_clientes_filtro_{n}.csv": ENCABEZADOS["fallas_clientes"]
            for n in range(1, partes + 1)},
    }


def validar_archivo(ruta: Path, campos: tuple[str, ...]) -> None:
    """Comprueba el encabezado sin recorrer de nuevo millones de filas."""
    if not ruta.is_file() or not ruta.stat().st_size:
        raise ValueError(f"Archivo ausente o vacío: {ruta}")
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        cabecera = archivo.readline()
    try:
        separador = csv.Sniffer().sniff(cabecera, delimiters=",|;\t").delimiter
        nombres = [c.strip().upper() for c in next(csv.reader([cabecera], delimiter=separador))]
    except csv.Error as exc:
        raise ValueError(f"{ruta.name}: no se reconoció el encabezado CSV") from exc
    faltan = set(campos) - set(nombres)
    if faltan or len(nombres) != len(set(nombres)):
        raise ValueError(f"{ruta.name}: encabezado inválido; columnas faltantes {sorted(faltan)}")


def listar_carpeta(gdown, url: str, destino: Path, esperados: dict) -> list[dict]:
    """Descubre todos los IDs, incluidas carpetas con más de 50 archivos."""
    remotos = gdown.download_folder(
        url=url, output=str(destino), quiet=True, skip_download=True,
        use_cookies=True, cookies_file=str(destino.parent / ".gdown_cookies.txt"), timeout=(15, 60))
    if not remotos:
        raise RuntimeError(f"No se pudo listar la carpeta pública: {url}")
    encontrados = {}
    for remoto in remotos:
        # Los destinos se construyen con nombres conocidos, no con rutas remotas.
        nombre = remoto.path
        if nombre == "caldenario_partidos_2026.csv":
            nombre = "calendario_partidos_2026.csv"
        if nombre not in esperados:
            if nombre.lower().endswith(".csv"):
                raise ValueError(f"CSV inesperado en {url}: {remoto.path}")
            continue
        if nombre in encontrados:
            raise ValueError(f"Archivo duplicado en Google Drive: {nombre}")
        encontrados[nombre] = {"id": remoto.id, "nombre": nombre, "nombre_drive": remoto.path}
    faltan = set(esperados) - set(encontrados)
    if faltan:
        raise ValueError(f"Carpeta pública incompleta ({url}); faltan: {sorted(faltan)}")
    return [encontrados[nombre] for nombre in esperados]


def preparar_datos(ruta_config: Path, solo_listar: bool = False) -> dict:
    raiz = ruta_config.resolve().parent
    conf = json.loads(ruta_config.read_text(encoding="utf-8"))
    base = raiz / conf["carpeta_datos"]
    esperados = archivos_esperados(conf)
    total = sum(len(nombres) for nombres in esperados.values())
    pendientes = {}
    for carpeta, nombres in esperados.items():
        destino = base / carpeta
        destino.mkdir(parents=True, exist_ok=True)
        pendientes[carpeta] = []
        for nombre, campos in nombres.items():
            ruta = destino / nombre
            if ruta.exists() and ruta.stat().st_size:
                validar_archivo(ruta, campos)
            else:
                pendientes[carpeta].append(nombre)
    region = base / "region_y_calendario"
    if (raiz / conf["dimension_region"]).resolve() != (region / "Dataset_Dim_Region.csv").resolve():
        raise ValueError("dimension_region debe apuntar a raw_data/region_y_calendario/Dataset_Dim_Region.csv")
    if (raiz / conf["calendario"]).resolve() != (region / "calendario_partidos_2026.csv").resolve():
        raise ValueError("calendario debe apuntar a raw_data/region_y_calendario/calendario_partidos_2026.csv")
    if not solo_listar and not any(pendientes.values()):
        print(f"Fuentes disponibles: {total} CSV en {base}; se reutilizan sin descargar.", flush=True)
        return {"archivos_esperados": total, "descargados": 0, "reutilizados": total}
    try:
        import gdown
    except ImportError as exc:
        raise RuntimeError("Instala las dependencias: python -m pip install -r requirements.txt") from exc
    fuentes = conf.get("fuentes_drive", {})
    planes = {}
    for carpeta, nombres in esperados.items():
        if not solo_listar and not pendientes[carpeta]:
            continue
        if not fuentes.get(carpeta):
            raise ValueError(f"Falta fuentes_drive.{carpeta} en config.json")
        print(f"Consultando Google Drive: {carpeta}...", flush=True)
        try:
            planes[carpeta] = listar_carpeta(gdown, fuentes[carpeta], base / carpeta, nombres)
        except (OSError, RuntimeError) as exc:
            raise RuntimeError(f"No se pudo consultar {carpeta} en Google Drive: {exc}") from exc
        print(f"  {len(planes[carpeta])} archivos verificados en la carpeta pública.", flush=True)
    if solo_listar:
        return {"archivos_esperados": total, "carpetas": planes}
    descargados = 0
    fallidos = []
    for carpeta, remotos in planes.items():
        for remoto in remotos:
            nombre = remoto["nombre"]
            if nombre not in pendientes[carpeta]:
                continue
            destino = base / carpeta / nombre
            # Un CSV vacío no es una descarga terminada y no debe omitirse al reanudar.
            if destino.exists() and not destino.stat().st_size:
                destino.unlink()
            print(f"Descargando {carpeta}/{nombre}...", flush=True)
            try:
                salida = gdown.download(
                    id=remoto["id"], output=str(destino), quiet=False,
                    user_agent=AGENTE_DESCARGA,
                    resume=True, use_cookies=True, cookies_file=str(base / ".gdown_cookies.txt"),
                    timeout=(15, 60), retries=3)
            except Exception as exc:
                fallidos.append((nombre, str(exc)))
                print(f"No se pudo descargar {nombre}; se continúa con los otros archivos.", flush=True)
                continue
            if not salida:
                fallidos.append((nombre, "Google Drive no devolvió el archivo"))
                continue
            validar_archivo(destino, esperados[carpeta][nombre])
            descargados += 1
    if fallidos:
        detalles = "\n".join(f"- {nombre}: {detalle}" for nombre, detalle in fallidos)
        raise RuntimeError(
            f"Quedan {len(fallidos)} descargas pendientes. Los archivos terminados se conservan. "
            "Revisa la conexión y los permisos/cuota de Google Drive; vuelve a ejecutar "
            f"scripts/descargar_datos.py para continuar. Detalles:\n{detalles}")
    for carpeta, nombres in esperados.items():
        for nombre, campos in nombres.items():
            validar_archivo(base / carpeta / nombre, campos)
    resumen = {"archivos_esperados": total, "descargados": descargados,
               "reutilizados": total - descargados}
    print(f"Fuentes listas: {total} CSV; {descargados} descargados en esta ejecución.", flush=True)
    return resumen
