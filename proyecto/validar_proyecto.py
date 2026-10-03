"""Valido el proyecto actual sin requerir notebooks ni documentos históricos.

Desde la raíz: python proyecto/validar_proyecto.py
Uso --exigir-resultados para exigir las salidas de main.py y sus manifiestos.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re

import nbformat

RAIZ = Path(__file__).resolve().parents[1]
ARCHIVOS = (
    "main.py", "config.json", "requirements.txt", "src/analisis.py", "src/descarga.py",
    "scripts/descargar_datos.py", "proyecto/eda.py", "proyecto/revision.py",
    "proyecto/validar_proyecto.py",
)
NOTEBOOKS = ("proyecto/proyecto_final_mineria_de_datos.ipynb",
             "proyecto/proyecto_final_mineria_de_datos_2.ipynb")


def validar(raiz=RAIZ, exigir_resultados=False, notebook=None):
    raiz = Path(raiz).resolve()
    faltan = [nombre for nombre in ARCHIVOS if not (raiz / nombre).is_file()]
    if faltan:
        raise FileNotFoundError("Faltan archivos del proyecto: " + ", ".join(faltan))
    if notebook is None:
        ruta = next((raiz / nombre for nombre in NOTEBOOKS if (raiz / nombre).is_file()), None)
        if ruta is None:
            raise FileNotFoundError("No encuentro un notebook del proyecto.")
    else:
        ruta = (raiz / notebook).resolve()
        if not ruta.is_relative_to(raiz / "proyecto") or ruta.suffix != ".ipynb":
            raise ValueError("Selecciono un notebook .ipynb dentro de proyecto/.")
        if not ruta.is_file():
            raise FileNotFoundError(ruta)
    notebook = nbformat.read(ruta, as_version=4)
    nbformat.validate(notebook)
    nombre_recursos = notebook.metadata.get("recursos_proyecto", "recursos")
    if nombre_recursos not in ("recursos", "recursos_2"):
        raise ValueError("La carpeta de recursos debe ser recursos o recursos_2.")
    recursos = raiz / "proyecto" / nombre_recursos
    textos = [c.source for c in notebook.cells if c.cell_type == "markdown"]
    codigo = [c for c in notebook.cells if c.cell_type == "code"]
    for i in range(1, 16):
        if not any(re.search(rf"^## {i}\. ", texto, re.M) for texto in textos):
            raise ValueError(f"No encuentro la sección {i} en el notebook.")
    prohibidos = r"eda_v\d|analisis_v\d|validar_v\d|/recursos_v\d|requirements_(?:eda|revision)_v\d|proyecto_final_v\d"
    for celda in codigo:
        if re.search(prohibidos, celda.source):
            raise ValueError("Una celda de código depende de una versión anterior.")
        fuente = "\n".join(l for l in celda.source.splitlines() if not l.lstrip().startswith("%"))
        ast.parse(fuente)
        if any(salida.output_type == "error" for salida in celda.get("outputs", [])):
            raise ValueError("El notebook guarda un error de ejecución.")
    for nombre in ("main.py", "scripts/descargar_datos.py", "proyecto/eda.py", "proyecto/revision.py"):
        if re.search(prohibidos, (raiz / nombre).read_text(encoding="utf-8-sig")):
            raise ValueError(f"{nombre} depende de una versión anterior.")
    dependencias = {}
    for linea in (raiz / "requirements.txt").read_text(encoding="utf-8").splitlines():
        if not linea.strip() or linea.lstrip().startswith("#"):
            continue
        nombre, version = linea.strip().split("==")
        instalada = importlib.metadata.version(nombre)
        if instalada != version:
            raise ValueError(f"{nombre}: requiero {version}, encuentro {instalada}. Instalo requirements.txt con este intérprete.")
        dependencias[nombre] = instalada
    enlaces_vigentes, enlaces_documentales_ausentes, resultados_ausentes = 0, [], []
    for texto in textos:
        for enlace in re.findall(r"\[[^\]]*\]\(([^)]+)\)", texto):
            enlace = enlace.split("#", 1)[0]
            if not enlace or re.match(r"^[a-zA-Z]+://", enlace):
                continue
            destino = (ruta.parent / enlace).resolve()
            if destino == (recursos / "validacion_proyecto.json").resolve():
                # Este informe se escribe al terminar la validación actual.
                enlaces_vigentes += 1
                continue
            if destino.is_file() or destino.is_dir():
                enlaces_vigentes += 1
            elif "resultados" in destino.parts or "raw_data" in destino.parts:
                resultados_ausentes.append(enlace)
            else:
                enlaces_documentales_ausentes.append(enlace)
    fuentes_salida = [
        "resultados/resumen_ejecucion.json", "resultados/control_calidad.json",
        "resultados/comparacion_periodo_zona.csv", "resultados/comparacion_diaria_zona.csv",
        "resultados/comparacion_por_partido_zona.csv", "resultados/alertas_ordenadas.csv",
        "resultados/fallas_generales_por_cliente.csv",
    ]
    salidas_faltantes = [p for p in fuentes_salida if not (raiz / p).is_file()]
    if exigir_resultados and salidas_faltantes:
        raise FileNotFoundError("Ejecuto primero main.py: " + ", ".join(salidas_faltantes))
    manifiestos_verificados = []
    for nombre in ("manifiesto_eda.json", "manifiesto_fuentes.json"):
        manifiesto = recursos / nombre
        if not manifiesto.is_file():
            if exigir_resultados:
                raise FileNotFoundError("Ejecuto las celdas del notebook para generar " + nombre)
            continue
        contenido = json.loads(manifiesto.read_text(encoding="utf-8"))
        # Los manifiestos documentales previos son opcionales y se conservan como históricos.
        if any(re.search(prohibidos, f["ruta"]) or "interpretacion" in f["ruta"] or
               f["ruta"].startswith("requisitos/") for f in contenido["fuentes"]):
            if exigir_resultados:
                raise ValueError("Regenero el manifiesto con las celdas del notebook: " + nombre)
            continue
        for fuente in contenido["fuentes"]:
            p = raiz / fuente["ruta"]
            if not p.is_file():
                raise FileNotFoundError(p)
            with p.open("rb") as archivo:
                huella = hashlib.file_digest(archivo, "sha256").hexdigest()
            if p.stat().st_size != fuente["bytes"] or huella != fuente["sha256"]:
                raise ValueError("El manifiesto difiere de la fuente " + fuente["ruta"])
        manifiestos_verificados.append(nombre)
    informe = dict(
        estructura_notebook_valida=True, notebook=str(ruta.relative_to(raiz)).replace("\\", "/"),
        recursos=str(recursos.relative_to(raiz)).replace("\\", "/"),
        celdas=len(notebook.cells), celdas_python=len(codigo),
        secciones_1_a_15=True, dependencias_instaladas=dependencias,
        referencias_a_versiones_anteriores_en_codigo=0, historico_necesario=False,
        enlaces_vigentes=enlaces_vigentes,
        enlaces_documentales_ausentes=sorted(set(enlaces_documentales_ausentes)),
        salidas_analiticas_faltantes=salidas_faltantes,
        manifiestos_verificados=manifiestos_verificados,
        alcance="Valido estructura, dependencias y rutas; no ejecuto main.py ni atribuyo causas a las fallas.",
    )
    if exigir_resultados and nombre_recursos == "recursos_2" and enlaces_documentales_ausentes:
        raise FileNotFoundError("Enlaces documentales ausentes: " + ", ".join(sorted(set(enlaces_documentales_ausentes))))
    recursos.mkdir(parents=True, exist_ok=True)
    (recursos / "validacion_proyecto.json").write_text(json.dumps(informe, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return informe


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raiz", type=Path, default=RAIZ)
    parser.add_argument("--exigir-resultados", action="store_true")
    parser.add_argument("--notebook", type=Path, help="Ruta del notebook respecto de la raíz.")
    args = parser.parse_args(argv)
    try:
        informe = validar(args.raiz, args.exigir_resultados, args.notebook)
    except (OSError, ValueError, importlib.metadata.PackageNotFoundError) as exc:
        parser.exit(1, str(exc)+"\n")
    print(json.dumps(informe, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
