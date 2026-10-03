"""Reproduzco el EDA del proyecto leyendo únicamente salidas agregadas existentes.

Desde la raíz del proyecto: python proyecto/eda.py
No ejecuto main.py ni abro las fuentes históricas o el índice SQLite.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
import statistics
from zoneinfo import ZoneInfo


FUENTES = (
    "config.json",
    "src/analisis.py",
    "resultados/control_calidad.json",
    "resultados/resumen_ejecucion.json",
    "resultados/comparacion_periodo_zona.csv",
    "resultados/comparacion_diaria_zona.csv",
    "resultados/comparacion_por_partido_zona.csv",
)
METRICAS = (
    "CLIENTES_DISTINTOS", "INCIDENCIAS_DISTINTAS", "MAC_DISTINTAS", "FALLAS_CLIENTE",
)
ANIOS = (2024, 2025, 2026)
COLORES = ("#49797D", "#6574AD", "#BE512D")


def leer_csv(ruta):
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        return list(csv.DictReader(archivo))


def cargar_salidas(raiz):
    """Compruebo fechas, referencias, cobertura, llaves y contadores guardados."""
    raiz = Path(raiz).resolve()
    faltantes = [nombre for nombre in FUENTES if not (raiz / nombre).is_file()]
    if faltantes:
        raise FileNotFoundError("Faltan las salidas del EDA: " + ", ".join(faltantes))
    conf, calidad, resumen = [
        json.loads((raiz / nombre).read_text(encoding="utf-8"))
        for nombre in (FUENTES[0], FUENTES[2], FUENTES[3])
    ]
    for clave in ("inicio_analisis", "fin_analisis", "anios_comparacion",
                  "minimo_ventanas_comparables"):
        if conf[clave] != resumen[clave]:
            raise ValueError(f"Config y resumen no coinciden en {clave}.")
    if conf["anios_comparacion"] != [2024, 2025]:
        raise ValueError("Este EDA documenta las referencias 2024 y 2025.")
    if (conf["inicio_analisis"], conf["fin_analisis"]) != ("2026-06-11", "2026-07-19"):
        raise ValueError("Este EDA documenta el periodo del 11 de junio al 19 de julio de 2026.")
    if int(conf["k_vecinos_distancia"]) != resumen["k_vecinos"]:
        raise ValueError("Config y resumen no coinciden en k.")
    if (int(conf["minutos_antes"]), int(conf["minutos_despues"])) != (30, 180):
        raise ValueError("La ventana vigente difiere de la documentada en el proyecto.")
    periodo, diario, partidos = [leer_csv(raiz / nombre) for nombre in FUENTES[4:]]
    for filas, contador, llaves in (
        (periodo, "filas_comparacion_periodo", ("NIVEL", "ZONA")),
        (diario, "filas_comparacion_diaria", ("FECHA_MX", "NIVEL", "ZONA")),
        (partidos, "filas_metricas", ("PARTIDO_ID", "NIVEL", "ZONA")),
    ):
        if len(filas) != resumen[contador]:
            raise ValueError(f"El contador {contador} no concuerda con el CSV.")
        if len({tuple(f[c] for c in llaves) for f in filas}) != len(filas):
            raise ValueError(f"Hay llaves repetidas en {contador}.")
        for fila in filas:
            if fila["COBERTURA_COMPLETA"] != "True":
                raise ValueError("Encuentro cobertura incompleta; reviso antes de comparar.")
            if fila["ANIOS_HISTORICOS_DISPONIBLES"] != "2024|2025":
                raise ValueError("Encuentro referencias históricas incompletas.")
            for metrica in METRICAS:
                for sufijo in ("", "_2024", "_2025"):
                    if not fila[metrica + sufijo] or int(fila[metrica + sufijo]) < 0:
                        raise ValueError(f"Conteo ausente o negativo en {metrica + sufijo}.")
                base = (int(fila[metrica + "_2024"]) + int(fila[metrica + "_2025"])) / 2
                if float(fila["PROMEDIO_HISTORICO_" + metrica]) != base:
                    raise ValueError("El promedio histórico no concuerda con los dos años.")
                if not fila["VAR_" + metrica + "_PCT_VS_HISTORICO"] and base != 0:
                    raise ValueError("Encuentro un porcentaje vacío con base positiva.")
            for sufijo in ("", "_2024", "_2025"):
                if (fila["FALLAS_PROMEDIO_POR_CLIENTE" + sufijo] == "") != (
                        int(fila["CLIENTES_DISTINTOS" + sufijo]) == 0):
                    raise ValueError("La ausencia de repetición media no concuerda con el denominador.")
    nacional = [f for f in periodo if f["NIVEL"] == "NACIONAL"]
    nacional_diario = sorted(
        (f for f in diario if f["NIVEL"] == "NACIONAL"), key=lambda f: f["FECHA_MX"])
    inicio, fin = [date.fromisoformat(conf[c]) for c in ("inicio_analisis", "fin_analisis")]
    esperados = [(inicio + timedelta(days=i)).isoformat() for i in range((fin-inicio).days+1)]
    if len(nacional) != 1 or [f["FECHA_MX"] for f in nacional_diario] != esperados:
        raise ValueError("No encuentro una fila nacional del periodo y la serie diaria completa.")
    if any(f["INICIO_MX"] != conf["inicio_analisis"] or
           f["FIN_MX"] != conf["fin_analisis"] for f in periodo):
        raise ValueError("Los extremos del CSV del periodo no coinciden con la configuración.")
    if len({f["PARTIDO_ID"] for f in partidos}) != resumen["partidos"]:
        raise ValueError("El número de partidos no concuerda con el resumen.")
    estados = Counter(f["ESTADO"] for f in partidos)
    if estados["ANOMALIA"] != resumen["alertas"]:
        raise ValueError("Las alertas no concuerdan con el resumen guardado.")
    if estados["SIN_BASE"] + estados["SIN_COBERTURA"] != resumen["filas_sin_base"]:
        raise ValueError("Las filas sin base no concuerdan con el resumen.")
    return dict(raiz=raiz, conf=conf, calidad=calidad, resumen=resumen,
                periodo=periodo, diario=diario, partidos=partidos,
                nacional=nacional[0], nacional_diario=nacional_diario)


def elaborar_perfil(datos):
    """Cuantifico faltantes, ceros, distribuciones y relaciones descriptivas."""
    faltantes = []
    for nombre in ("periodo", "diario", "partidos"):
        filas = datos[nombre]
        denominador_cero = sum(int(f["CLIENTES_DISTINTOS"]) == 0 for f in filas)
        porcentaje_vacio = sum(f["VAR_CLIENTES_DISTINTOS_PCT_VS_HISTORICO"] == "" for f in filas)
        faltantes.append({
            "tabla": nombre, "filas": len(filas),
            "conteos_vacios": sum(any(f[c] == "" for c in METRICAS) for f in filas),
            "sin_clientes_2026": denominador_cero,
            "repeticion_media_vacia": sum(f["FALLAS_PROMEDIO_POR_CLIENTE"] == "" for f in filas),
            "porcentaje_clientes_vacio": porcentaje_vacio,
            "porcentaje_vacio_pct_filas": round(100 * porcentaje_vacio / len(filas), 2),
            "base_historica_clientes_cero": sum(float(f["PROMEDIO_HISTORICO_CLIENTES_DISTINTOS"]) == 0 for f in filas),
        })
    distribucion = []
    for anio, sufijo in zip(ANIOS, ("_2024", "_2025", "")):
        x = [int(f["CLIENTES_DISTINTOS" + sufijo]) for f in datos["nacional_diario"]]
        q1, mediana, q3 = statistics.quantiles(x, n=4, method="inclusive")
        distribucion.append(dict(anio=anio, dias=len(x), minimo=min(x), q1=q1,
                                 mediana=mediana, q3=q3, maximo=max(x)))
    ventanas = [f for f in datos["partidos"] if f["NIVEL"] == "NACIONAL"]
    perfil_variables = []
    for columna in METRICAS[:3]:
        x = [int(f[columna]) for f in ventanas]
        perfil_variables.append(dict(variable=columna, ventanas=len(x), minimo=min(x),
                                      mediana=statistics.median(x), maximo=max(x)))
    correlaciones = {}
    for columna in ("INCIDENCIAS_DISTINTAS", "MAC_DISTINTAS"):
        clientes = [int(f["CLIENTES_DISTINTOS"]) for f in ventanas]
        valores = [int(f[columna]) for f in ventanas]
        correlaciones[columna] = (round(statistics.correlation(clientes, valores), 4)
                                  if len(clientes) > 1 and len(set(clientes)) > 1
                                  and len(set(valores)) > 1 else None)
    entidades = sorted(
        (f for f in datos["periodo"] if f["NIVEL"] == "ENTIDAD_FEDERATIVA"),
        key=lambda f: float(f["DIF_FALLAS_CLIENTE_VS_HISTORICO"]), reverse=True)
    alertas = [f for f in datos["partidos"] if f["ESTADO"] == "ANOMALIA"]
    return dict(
        faltantes=faltantes, distribucion_diaria=distribucion,
        dias_clientes_sobre_historico=sum(float(f["DIF_CLIENTES_DISTINTOS_VS_HISTORICO"]) > 0
                                         for f in datos["nacional_diario"]),
        pico_clientes=max(datos["nacional_diario"], key=lambda f: int(f["CLIENTES_DISTINTOS"])),
        perfil_variables_ventanas=perfil_variables, correlaciones_ventanas=correlaciones,
        entidades_top5=entidades[:5],
        entidades_aumento_fallas=sum(float(f["DIF_FALLAS_CLIENTE_VS_HISTORICO"]) > 0 for f in entidades),
        estados=dict(Counter(f["ESTADO"] for f in datos["partidos"])),
        referencias=dict(Counter(f["N_REFERENCIAS"] for f in datos["partidos"])),
        alertas_con_ambos_historicos_cero=sum(
            int(f["CLIENTES_DISTINTOS_2024"]) == int(f["CLIENTES_DISTINTOS_2025"]) == 0 for f in alertas),
    )


def formato(valor, decimales=0):
    if valor is None or valor == "":
        return "No disponible"
    return f"{float(valor):,.{decimales}f}".replace(",", "_").replace(".", ",").replace("_", ".")


def tabla_markdown(encabezados, filas):
    return "\n".join([
        "| " + " | ".join(encabezados) + " |",
        "| " + " | ".join("---" for _ in encabezados) + " |",
        *("| " + " | ".join(map(str, fila)) + " |" for fila in filas),
    ])


def grafica_evolucion(datos):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    filas = datos["nacional_diario"]
    fig, ax = plt.subplots(figsize=(11.6, 5.5), layout="constrained")
    fig.set_facecolor("#FAFAF8")
    ax.set_facecolor("#FAFAF8")
    x = list(range(len(filas)))
    for anio, sufijo, color in zip(ANIOS, ("_2024", "_2025", ""), COLORES):
        ax.plot(x, [int(f["CLIENTES_DISTINTOS" + sufijo]) / 1000 for f in filas],
                label=str(anio), color=color, linewidth=2.6 if anio == 2026 else 1.6,
                alpha=1 if anio == 2026 else .8)
    ax.plot(x, [float(f["PROMEDIO_HISTORICO_CLIENTES_DISTINTOS"]) / 1000 for f in filas],
            label="Promedio 2024–2025", color="#545454", linestyle="--", linewidth=1.7)
    pico = max(range(len(filas)), key=lambda i: int(filas[i]["CLIENTES_DISTINTOS"]))
    y_pico = int(filas[pico]["CLIENTES_DISTINTOS"]) / 1000
    fecha_pico = date.fromisoformat(filas[pico]["FECHA_MX"])
    rotulo_pico = f"{fecha_pico.day} de " + ("junio" if fecha_pico.month == 6 else "julio")
    porcentaje_pico = formato(filas[pico]["VAR_CLIENTES_DISTINTOS_PCT_VS_HISTORICO"], 2)
    ax.scatter([pico], [y_pico], color=COLORES[2], s=45, zorder=5)
    ax.annotate(f"{rotulo_pico}: {formato(y_pico*1000)} clientes\n"
                f"{porcentaje_pico} % frente al promedio histórico",
                xy=(pico, y_pico), xytext=(pico+3, y_pico-15), fontsize=10,
                arrowprops=dict(arrowstyle="->", color="#4A4A4A"), va="top")
    marcas = list(range(0, len(filas), 5))
    if marcas[-1] != len(filas)-1:
        marcas.append(len(filas)-1)
    ax.set_xticks(marcas, [f"{int(filas[i]['FECHA_MX'][8:])} " +
                          ("jun" if filas[i]["FECHA_MX"][5:7] == "06" else "jul") for i in marcas])
    maximo = max(int(f["CLIENTES_DISTINTOS" + s]) / 1000
                 for f in filas for s in ("", "_2024", "_2025"))
    ax.set_ylim(bottom=0, top=max(520, maximo*1.12))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: formato(v)))
    ax.set_ylabel("Clientes distintos afectados por día (miles)")
    ax.set_xlabel("Mismo mes y día en cada año · America/Mexico_City")
    ax.set_title(f"La evolución diaria de 2026 presenta un pico el {rotulo_pico}",
                 loc="left", pad=19, weight="bold")
    ax.grid(axis="y", alpha=.18)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, loc="upper right")
    return fig


def grafica_distribucion(datos):
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    series = [[int(f["CLIENTES_DISTINTOS" + sufijo]) / 1000 for f in datos["nacional_diario"]]
              for sufijo in ("_2024", "_2025", "")]
    fig, ax = plt.subplots(figsize=(9.2, 5.5), layout="constrained")
    fig.set_facecolor("#FAFAF8")
    ax.set_facecolor("#FAFAF8")
    cajas = ax.boxplot(series, tick_labels=[str(a) for a in ANIOS], patch_artist=True,
                      widths=.4, showfliers=False,
                      medianprops=dict(color="#232323", linewidth=2))
    for i, (serie, color, caja) in enumerate(zip(series, COLORES, cajas["boxes"]), start=1):
        caja.set_facecolor(color)
        caja.set_alpha(.25)
        caja.set_edgecolor(color)
        # Desplazamiento determinístico: muestro los 39 días sin duplicar los puntos extremos.
        offsets = [((j % 7)-3) * .024 for j in range(len(serie))]
        ax.scatter([i+v for v in offsets], serie, color=color, alpha=.65, s=25, zorder=3)
        mediana = statistics.median(serie)
        ax.text(i+.25, mediana, formato(mediana*1000), fontsize=10, va="center", weight="bold")
    ax.set_ylim(bottom=0, top=max(520, max(map(max, series))*1.12))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: formato(v)))
    ax.set_ylabel("Clientes distintos afectados por día (miles)")
    ax.set_xlabel(f"{len(series[0])} días por año · cada punto representa un día")
    titulo = ("La mediana diaria de clientes afectados es mayor en 2026"
              if statistics.median(series[2]) > max(map(statistics.median, series[:2]))
              else "Comparo la distribución diaria de clientes afectados")
    ax.set_title(titulo, loc="left", pad=19, weight="bold")
    ax.grid(axis="y", alpha=.18)
    ax.spines[["top", "right"]].set_visible(False)
    return fig


def guardar_figura(figura, carpeta, nombre):
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "svg"):
        figura.savefig(carpeta / f"{nombre}.{extension}", dpi=160,
                       metadata={"Creator": "EDA del proyecto"} if extension == "svg" else None)


def exportar_perfil(datos, perfil, carpeta):
    import matplotlib
    import platform

    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    manifiesto = dict(
        fecha_revision=datetime.now(ZoneInfo("America/Mexico_City")).isoformat(),
        python=platform.python_version(),
        matplotlib=matplotlib.__version__,
        alcance="Salidas existentes; no regenero main.py ni leo fuentes históricas originales.",
        fuentes=[dict(ruta=nombre, bytes=(datos["raiz"] / nombre).stat().st_size,
                      sha256=hashlib.sha256((datos["raiz"] / nombre).read_bytes()).hexdigest())
                 for nombre in (*FUENTES, "proyecto/eda.py", "requirements.txt")],
    )
    for nombre, contenido in (("perfil_eda.json", perfil), ("manifiesto_eda.json", manifiesto)):
        (carpeta / nombre).write_text(json.dumps(contenido, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv=None):
    import argparse
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raiz", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)
    try:
        datos = cargar_salidas(args.raiz)
    except FileNotFoundError as exc:
        parser.exit(1, f"{exc}\nEjecuto primero main.py para generar las salidas.\n")
    perfil = elaborar_perfil(datos)
    carpeta = datos["raiz"] / "proyecto" / "recursos"
    for nombre, generar in (("evolucion_clientes_diaria", grafica_evolucion),
                            ("distribucion_clientes_diaria", grafica_distribucion)):
        figura = generar(datos)
        guardar_figura(figura, carpeta, nombre)
        plt.close(figura)
    exportar_perfil(datos, perfil, carpeta)
    print(f"Reproduje dos gráficas y sus perfiles en {carpeta}.")


if __name__ == "__main__":
    main()
