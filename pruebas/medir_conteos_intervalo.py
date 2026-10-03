"""Compara consultas sobre el índice existente, sin reconstruirlo ni modificarlo.

Uso: python -m pruebas.medir_conteos_intervalo --salida resultados/medicion_conteos.json
"""

import argparse
from contextlib import closing
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
from time import perf_counter

from src.analisis import cuenta_intervalo_todos, cuenta_ventana, leer_partidos, periodos_analisis


def medir(config: Path, salida: Path):
    conf = json.loads(config.read_text(encoding="utf-8"))
    raiz = config.resolve().parent
    indice = raiz / conf["carpeta_resultados"] / "_indice_temporal.sqlite"
    niveles = [None, *conf["niveles_geograficos"]]
    partido = leer_partidos(raiz / conf["calendario"])[0]["inicio"]
    dia = partido.replace(hour=0, minute=0, second=0, microsecond=0)
    intervalos = {
        "ventana_partido": (partido - timedelta(minutes=conf["minutos_antes"]),
                            partido + timedelta(minutes=conf["minutos_despues"])),
        "dia": (dia, dia + timedelta(days=1)),
        "periodo": periodos_analisis(conf)[partido.year],
    }
    resultados = {"sqlite": sqlite3.sqlite_version, "indice": str(indice),
                  "metodo": "Una medición por variante e intervalo, original primero; "
                            "la caché de disco puede favorecer la segunda consulta.",
                  "intervalos": []}
    with closing(sqlite3.connect(indice.resolve().as_uri() + "?mode=ro", uri=True)) as con:
        con.execute("PRAGMA query_only=ON")
        con.execute("PRAGMA temp_store=FILE")
        con.execute("PRAGMA cache_size=-65536")
        for nombre, (inicio, fin) in intervalos.items():
            consultas = []
            con.set_trace_callback(consultas.append)
            print(f"{nombre}: consultas originales ({len(niveles)} niveles)...", flush=True)
            t = perf_counter()
            original = {nivel: cuenta_ventana(con, inicio, fin, nivel) for nivel in niveles}
            segundos_original = perf_counter() - t
            consultas_original = len(consultas)
            consultas.clear()
            print(f"{nombre}: consulta materializada...", flush=True)
            t = perf_counter()
            nuevo = cuenta_intervalo_todos(con, inicio, fin, niveles)
            segundos_nuevo = perf_counter() - t
            con.set_trace_callback(None)
            if original != nuevo:
                raise AssertionError(f"Los conteos cambiaron en {nombre}; no integrar la mejora")
            plan = [r[3] for r in con.execute("EXPLAIN QUERY PLAN " + consultas[0])]
            fila = {"intervalo": nombre, "inicio": str(inicio), "fin_exclusivo": str(fin),
                    "conteos_iguales": True, "segundos_original": round(segundos_original, 4),
                    "segundos_materializada": round(segundos_nuevo, 4),
                    "consultas_original": consultas_original, "consultas_materializada": len(consultas),
                    "conteos_nacionales": nuevo.get(None, {}),
                    "zonas_por_nivel": {nivel or "NACIONAL": len(zonas)
                                        for nivel, zonas in nuevo.items()},
                    "plan_materializada": plan}
            resultados["intervalos"].append(fila)
            print(json.dumps({k: v for k, v in fila.items() if not k.startswith("plan")},
                             ensure_ascii=False), flush=True)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(json.dumps(resultados, ensure_ascii=False, indent=2), encoding="utf-8")
    return resultados


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("config.json"))
    parser.add_argument("--salida", type=Path, required=True)
    args = parser.parse_args()
    medir(args.config, args.salida)
