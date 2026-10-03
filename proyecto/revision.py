"""Reviso las salidas y la sensibilidad sin depender de versiones anteriores.

Desde la raíz: python proyecto/revision.py
Exporto los auxiliares de cada notebook por separado; no abro fuentes originales ni SQLite.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from proyecto.eda import cargar_salidas, elaborar_perfil, formato, tabla_markdown
from src.analisis import evaluar

VARIABLES = ("CLIENTES_DISTINTOS", "INCIDENCIAS_DISTINTAS", "MAC_DISTINTAS")
METRICAS = (*VARIABLES, "FALLAS_CLIENTE")
FUENTES = (
    "config.json", "src/analisis.py", "proyecto/eda.py",
    "resultados/control_calidad.json", "resultados/resumen_ejecucion.json",
    "resultados/comparacion_periodo_zona.csv", "resultados/comparacion_diaria_zona.csv",
    "resultados/comparacion_por_partido_zona.csv", "resultados/alertas_ordenadas.csv",
    "resultados/fallas_generales_por_cliente.csv",
    "proyecto/revision.py", "requirements.txt",
)


def clave(fila):
    return (fila["PARTIDO_ID"], fila["NIVEL"], fila["ZONA"])


def clave_horario(fila):
    return (fila["INICIO_MX"], fila["NIVEL"], fila["ZONA"])


def vectores(fila):
    actual = tuple(int(fila[v]) for v in VARIABLES)
    controles = [tuple(int(fila[f"{v}_{a}"]) for v in VARIABLES) for a in (2024, 2025)]
    return actual, controles


def leer_json(raiz, nombre):
    return json.loads((raiz / nombre).read_text(encoding="utf-8-sig"))


def revisar_clientes(raiz, nacional, resumen):
    """Recalculo agregados en flujo y compruebo identificadores únicos y ordenados."""
    ruta = raiz / "resultados/fallas_generales_por_cliente.csv"
    if not ruta.is_file():
        raise FileNotFoundError(f"Falta {ruta.name}; ejecuto primero main.py.")
    afectados = {str(a): 0 for a in (2024, 2025, 2026)}
    pares = afectados.copy()
    histograma = Counter()
    cohorte = dict(clientes=0, **{str(a): 0 for a in (2024, 2025, 2026)})
    previo, filas, solo_2026 = None, 0, 0
    with ruta.open(encoding="utf-8-sig", newline="") as archivo:
        lector = csv.DictReader(archivo)
        requeridos = {"WIDMT_CLIENTE", "FALLAS_2024", "FALLAS_2025", "FALLAS_2026", "COBERTURA_COMPLETA"}
        if not requeridos.issubset(lector.fieldnames or []):
            raise ValueError("Faltan columnas en el CSV por cliente.")
        for fila in lector:
            cliente = fila["WIDMT_CLIENTE"]
            if not cliente or (previo is not None and cliente <= previo):
                raise ValueError("Encuentro clientes vacíos, repetidos o fuera del orden esperado.")
            previo = cliente
            if fila["COBERTURA_COMPLETA"] != "True":
                raise ValueError("No calculo recurrencia con cobertura incompleta.")
            valores = {str(a): int(fila[f"FALLAS_{a}"]) for a in (2024, 2025, 2026)}
            if any(v < 0 for v in valores.values()):
                raise ValueError("Encuentro un conteo negativo por cliente.")
            for a, valor in valores.items():
                afectados[a] += valor > 0
                pares[a] += valor
            histograma[valores["2026"]] += 1
            solo_2026 += valores["2026"] > 0 and valores["2024"] == valores["2025"] == 0
            if all(valores.values()):
                cohorte["clientes"] += 1
                for a, valor in valores.items():
                    cohorte[a] += valor
            filas += 1
    if filas != resumen["clientes_comparados"]:
        raise ValueError("El número de clientes no coincide con el resumen.")
    for a in (2024, 2025, 2026):
        sufijo = "" if a == 2026 else f"_{a}"
        if afectados[str(a)] != int(nacional["CLIENTES_DISTINTOS"+sufijo]):
            raise ValueError("Los clientes del CSV no coinciden con el nacional.")
        if pares[str(a)] != int(nacional["FALLAS_CLIENTE"+sufijo]):
            raise ValueError("Los pares del CSV no coinciden con el nacional.")
    return dict(filas_revisadas=filas, afectados_por_anio=afectados, fallas_por_anio=pares,
                histograma_fallas_2026=dict(sorted(histograma.items())), solo_con_fallas_en_2026=solo_2026,
                cohorte_con_fallas_en_los_tres_anios=cohorte)


def comprobar_aritmetica(datos):
    comprobadas = 0
    for filas in (datos["periodo"], datos["diario"], datos["partidos"]):
        for fila in filas:
            for metrica in METRICAS:
                actual = int(fila[metrica])
                referencias = {str(a): int(fila[f"{metrica}_{a}"]) for a in (2024, 2025)}
                referencias["HISTORICO"] = sum(referencias.values()) / 2
                for referencia, base in referencias.items():
                    diferencia = float(fila[f"DIF_{metrica}_VS_{referencia}"])
                    porcentaje = fila[f"VAR_{metrica}_PCT_VS_{referencia}"]
                    if diferencia != actual - base:
                        raise ValueError(f"Diferencia inconsistente: {metrica} / {referencia}.")
                    if base == 0:
                        if porcentaje != "":
                            raise ValueError("Encuentro un porcentaje definido con denominador cero.")
                    elif not math.isclose(float(porcentaje), round(100 * (actual-base)/base, 2), abs_tol=1e-8):
                        raise ValueError("Encuentro un porcentaje inconsistente.")
                for sufijo in ("", "_2024", "_2025"):
                    clientes = int(fila["CLIENTES_DISTINTOS" + sufijo])
                    repeticion = fila["FALLAS_PROMEDIO_POR_CLIENTE" + sufijo]
                    esperado = round(int(fila["FALLAS_CLIENTE" + sufijo])/clientes, 4) if clientes else None
                    if esperado is not None and float(repeticion) != esperado:
                        raise ValueError("Encuentro una repetición media inconsistente.")
            comprobadas += 1
    return comprobadas


def revisar(raiz=RAIZ):
    raiz = Path(raiz).resolve()
    datos = cargar_salidas(raiz)
    filas, conf = datos["partidos"], datos["conf"]
    comprobadas = comprobar_aritmetica(datos)
    recalculadas = []
    for fila in filas:
        actual, controles = vectores(fila)
        resultado = evaluar(actual, controles, conf)
        for campo, valor in resultado.items():
            guardado = fila[campo]
            igual = (str(valor) == guardado if isinstance(valor, str)
                     else math.isclose(float(valor), float(guardado), abs_tol=1e-8))
            if not igual:
                raise ValueError(f"Evaluación distinta en {clave(fila)}: {campo}.")
        recalculadas.append(resultado)
    with (raiz / "resultados/alertas_ordenadas.csv").open(encoding="utf-8-sig", newline="") as archivo:
        alertas = list(csv.DictReader(archivo))
    esperadas = [f for f in filas if f["ESTADO"] == "ANOMALIA"]
    esperadas.sort(key=lambda f: float(f["EXCESO_CLIENTES"]), reverse=True)
    if alertas != esperadas:
        raise ValueError("La selección o el orden de las alertas difieren de las comparaciones.")

    estados = dict(Counter(f["ESTADO"] for f in filas))
    distintos = {}
    for f in filas:
        k = clave_horario(f)
        if k in distintos and (vectores(f), f["ESTADO"]) != (vectores(distintos[k]), distintos[k]["ESTADO"]):
            raise ValueError("El mismo horario y territorio tienen evaluaciones diferentes.")
        distintos[k] = f
    por_nivel = [dict(nivel=n, evaluaciones=sum(f["NIVEL"] == n for f in filas),
                     alertas=sum(f["NIVEL"] == n and f["ESTADO"] == "ANOMALIA" for f in filas))
                 for n in ("NACIONAL", "ENTIDAD_FEDERATIVA", "HUB_CM", "PLAZA")]
    alertas_cero = sum(int(f["CLIENTES_DISTINTOS_2024"]) == int(f["CLIENTES_DISTINTOS_2025"]) == 0 for f in alertas)
    alertas_menos10 = sum(float(f["PROMEDIO_HISTORICO_CLIENTES_DISTINTOS"]) < 10 for f in alertas)
    entidades = sorted((f for f in datos["periodo"] if f["NIVEL"] == "ENTIDAD_FEDERATIVA"),
                        key=lambda f: float(f["DIF_FALLAS_CLIENTE_VS_HISTORICO"]), reverse=True)
    incremento = float(datos["nacional"]["DIF_FALLAS_CLIENTE_VS_HISTORICO"])
    participacion = (sum(float(f["DIF_FALLAS_CLIENTE_VS_HISTORICO"]) for f in entidades[:2])
                     / incremento * 100 if incremento else None)
    picos = [f for f in datos["nacional_diario"] if f["FECHA_MX"] in ("2026-06-18", "2026-06-19")]
    pares_picos = sum(float(f["DIF_FALLAS_CLIENTE_VS_HISTORICO"]) for f in picos)
    clientes = revisar_clientes(raiz, datos["nacional"], datos["resumen"])
    histograma = {int(k): v for k, v in clientes["histograma_fallas_2026"].items()}
    afectados = int(datos["nacional"]["CLIENTES_DISTINTOS"])
    if sum(n for k, n in histograma.items() if k > 0) != afectados:
        raise ValueError("El histograma previo no concuerda con clientes afectados de 2026.")
    if sum(k*n for k, n in histograma.items()) != int(datos["nacional"]["FALLAS_CLIENTE"]):
        raise ValueError("El histograma previo no concuerda con los pares de 2026.")
    for a in (2024, 2025, 2026):
        sufijo = "" if a == 2026 else f"_{a}"
        if clientes["afectados_por_anio"][str(a)] != int(datos["nacional"]["CLIENTES_DISTINTOS"+sufijo]):
            raise ValueError("El agregado por cliente difiere del total nacional.")
        if clientes["fallas_por_anio"][str(a)] != int(datos["nacional"]["FALLAS_CLIENTE"+sufijo]):
            raise ValueError("El agregado de pares difiere del total nacional.")
    indicadores = dict(
        estados=estados, por_nivel=por_nivel, alertas= len(alertas), evaluaciones=len(filas),
        porcentaje_alertas=100*len(alertas)/len(filas),
        evaluaciones_horario_distinto=len(distintos),
        alertas_horario_distinto=sum(f["ESTADO"] == "ANOMALIA" for f in distintos.values()),
        horarios_distintos=len({f["INICIO_MX"] for f in filas}),
        alertas_cero=alertas_cero, alertas_menos10=alertas_menos10,
        porcentaje_alertas_cero=100*alertas_cero/len(alertas) if alertas else None,
        porcentaje_alertas_menos10=100*alertas_menos10/len(alertas) if alertas else None,
        top_entidades=entidades[:5], participacion_dos_entidades=participacion,
        entidades_aumento=sum(float(f["DIF_FALLAS_CLIENTE_VS_HISTORICO"]) > 0 for f in entidades),
        dias_aumento_clientes=sum(float(f["DIF_CLIENTES_DISTINTOS_VS_HISTORICO"]) > 0 for f in datos["nacional_diario"]),
        dias_aumento_pares=sum(float(f["DIF_FALLAS_CLIENTE_VS_HISTORICO"]) > 0 for f in datos["nacional_diario"]),
        pares_adicionales_picos=pares_picos,
        porcentaje_incremento_picos=100*pares_picos/incremento if incremento else None,
        recurrencia=[dict(categoria=nombre, clientes=sum(n for k,n in histograma.items() if condicion(k)))
                     for nombre, condicion in (("Exactamente una", lambda k: k == 1),
                                               ("Dos o más", lambda k: k >= 2),
                                               ("Cinco o más", lambda k: k >= 5),
                                               ("Diez o más", lambda k: k >= 10))],
        clientes=clientes,
    )
    escenarios = sensibilidad(filas, conf)
    return dict(datos=datos, perfil=elaborar_perfil(datos), indicadores=indicadores,
                sensibilidad=escenarios,
                verificacion=dict(filas_aritmetica=comprobadas, evaluaciones_recalculadas=len(recalculadas),
                                  diferencias_evaluador=0, seleccion_orden_alertas_exactos=True,
                                  filas_clientes_recalculadas=clientes["filas_revisadas"],
                                  agregados_clientes_conciliados=True))


def sensibilidad(filas, conf):
    """Cambio un parámetro a la vez; no sobrescribo config ni las salidas originales."""
    escenarios = (
        ("Configuración actual", {}),
        ("Puntuación mínima = 2", {"minimo_puntuacion_distancia": 2.0}),
        ("Puntuación mínima = 4", {"minimo_puntuacion_distancia": 4.0}),
        ("Puntuación mínima = 6", {"minimo_puntuacion_distancia": 6.0}),
        ("Clientes mínimos = 25", {"minimo_clientes_anomalia": 25}),
        ("Clientes mínimos = 100", {"minimo_clientes_anomalia": 100}),
        ("Exceso mínimo = 25", {"minimo_exceso_clientes": 25}),
        ("Exceso mínimo = 100", {"minimo_exceso_clientes": 100}),
        ("Mínimo de 3 referencias", {"minimo_ventanas_comparables": 3}),
        ("Configuración anterior: 6 referencias, k=3",
         {"minimo_ventanas_comparables": 6, "k_vecinos_distancia": 3}),
    )
    originales = {clave(f) for f in filas if f["ESTADO"] == "ANOMALIA"}
    resultados = []
    for nombre, cambios in escenarios:
        parametros = {**conf, **cambios}
        clases = [(f, evaluar(*vectores(f), parametros)["ESTADO"]) for f in filas]
        estados = Counter(estado for _, estado in clases)
        alertas = {clave(f) for f, estado in clases if estado == "ANOMALIA"}
        union, interseccion = alertas | originales, alertas & originales
        resultados.append(dict(
            escenario=nombre, minimo_referencias=parametros["minimo_ventanas_comparables"],
            k=parametros["k_vecinos_distancia"], puntuacion_minima=parametros["minimo_puntuacion_distancia"],
            clientes_minimos=parametros["minimo_clientes_anomalia"],
            exceso_minimo=parametros["minimo_exceso_clientes"],
            alertas=estados["ANOMALIA"], esperados=estados["ESPERADO"], sin_base=estados["SIN_BASE"],
            alertas_horario_distinto=len({clave_horario(f) for f, estado in clases if estado == "ANOMALIA"}),
            retenidas=len(interseccion), nuevas=len(alertas-originales), retiradas=len(originales-alertas),
            jaccard=round(len(interseccion)/len(union), 6) if union else 1.0,
        ))
    return resultados


def exportar(revision, carpeta=None):
    raiz = revision["datos"]["raiz"]
    carpeta = Path(carpeta) if carpeta else raiz / "proyecto/recursos"
    permitidas = {(raiz / "proyecto" / nombre).resolve()
                  for nombre in ("recursos", "recursos_2")}
    if carpeta.resolve() not in permitidas:
        raise ValueError("Exporto a proyecto/recursos o proyecto/recursos_2.")
    carpeta.mkdir(parents=True, exist_ok=True)
    resumen = dict(fecha_revision=datetime.now(ZoneInfo("America/Mexico_City")).isoformat(),
                   alcance="Salidas agregadas y reportes guardados; no reproceso fuentes ni índices.",
                   configuracion_detector={k: revision["datos"]["conf"][k] for k in (
                       "minimo_ventanas_comparables", "k_vecinos_distancia", "minimo_clientes_anomalia",
                       "minimo_exceso_clientes", "minimo_puntuacion_distancia", "minutos_antes", "minutos_despues")},
                   verificacion=revision["verificacion"], indicadores=revision["indicadores"],
                   sensibilidad=revision["sensibilidad"])
    (carpeta / "resumen_revision.json").write_text(json.dumps(resumen, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    with (carpeta / "sensibilidad_detector.csv").open("w", encoding="utf-8-sig", newline="") as archivo:
        escritor = csv.DictWriter(archivo, fieldnames=list(revision["sensibilidad"][0]))
        escritor.writeheader()
        escritor.writerows(revision["sensibilidad"])
    manifiesto = dict(fecha_revision=resumen["fecha_revision"], fuentes=[])
    for nombre in FUENTES:
        p = raiz / nombre
        with p.open("rb") as archivo:
            huella = hashlib.file_digest(archivo, "sha256").hexdigest()
        manifiesto["fuentes"].append(dict(ruta=nombre, bytes=p.stat().st_size, sha256=huella))
    (carpeta / "manifiesto_fuentes.json").write_text(json.dumps(manifiesto, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return carpeta


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raiz", type=Path, default=RAIZ)
    args = parser.parse_args(argv)
    try:
        revision = revisar(args.raiz)
    except FileNotFoundError as exc:
        parser.exit(1, f"{exc}\nEjecuto primero main.py para generar las salidas.\n")
    exportar(revision)
    print(json.dumps(revision["verificacion"], ensure_ascii=False))
    for escenario in revision["sensibilidad"]:
        print(f"{escenario['escenario']}: {escenario['alertas']} alertas; {escenario['sin_base']} sin base.")


if __name__ == "__main__":
    main()
