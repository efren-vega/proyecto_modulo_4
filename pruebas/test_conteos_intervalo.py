"""Equivalencia con la consulta original, deduplicación y reutilización de intervalos."""

import csv
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from src.analisis import (NIVELES, analizar, comparar_intervalos, crear_base,
                          cuenta_intervalo_todos, cuenta_ventana, evaluar)


NIVELES_ANALISIS = [None, "ENTIDAD_FEDERATIVA", "HUB_CM", "PLAZA"]


def conteos_originales(con, inicio, fin, niveles):
    return {nivel: cuenta_ventana(con, inicio, fin, nivel) for nivel in niveles}


class ConteosIntervalo(unittest.TestCase):
    def setUp(self):
        self.con = sqlite3.connect(":memory:")
        self.addCleanup(self.con.close)
        crear_base(self.con)
        self.con.executemany("INSERT INTO regiones VALUES (?, ?, ?, ?, ?, ?)", [
            ("r1", "CENTRO", "METRO", "CDMX", "H1", "P1"),
            ("r2", "CENTRO", "METRO", "CDMX", "H2", "P2"),
            ("r3", "OCCIDENTE", "OESTE", "JALISCO", "H3", "P3"),
            ("r4", None, "", "", None, ""),
        ])
        for anio in (2024, 2025, 2026):
            inicio = datetime(anio, 6, 11, 12, 30)
            for n in range(1, 7):
                self.con.execute("INSERT INTO incidencias VALUES (?, ?)",
                                 (f"{anio}-i{n}", inicio.isoformat(sep=" ")))
            filas = [
                ("i1", "c1", "m1", "r1", inicio),
                ("i1", "c1", "m1", "r1", inicio),  # Otro id; mismo dato de negocio.
                ("i1", "c1", "m2", "r1", inicio),
                ("i1", "c1", "m1", "r2", inicio),
                ("i1", "c1", "m1", "r3", inicio),
                ("i2", "c1", "m1", "r1", inicio + timedelta(minutes=30)),
                ("i2", "c2", None, "r1", inicio + timedelta(minutes=30)),
                ("i3", "c3", "m3", "r4", inicio + timedelta(minutes=90)),
                ("i4", "c1", "m1", "r1", inicio + timedelta(days=1)),
                ("i5", "c_fin", "m_fin", "r1", inicio + timedelta(minutes=210)),
                ("i6", "c_antes", "m_antes", "r1", inicio - timedelta(seconds=1)),
                ("huerfana", "c_sin_ir", "m_sin_ir", "r1", inicio),
                ("i1", "c_sin_region", "m_sin_region", "ausente", inicio),
            ]
            self.con.executemany("INSERT INTO afectados VALUES (?, ?, ?, ?, ?, ?)",
                [(f"{anio}-{n}", f"{anio}-{inc}", cliente, mac, region,
                  fecha.isoformat(sep=" "))
                 for n, (inc, cliente, mac, region, fecha) in enumerate(filas)])
        self.con.execute("CREATE INDEX idx_afectados_fecha ON afectados(fecha_mx)")
        self.inicio = datetime(2026, 6, 11, 12, 30)
        self.fin = datetime(2026, 6, 11, 16)

    def contar(self, inicio=None, fin=None, niveles=None):
        return cuenta_intervalo_todos(self.con, inicio or self.inicio, fin or self.fin,
                                     NIVELES_ANALISIS if niveles is None else niveles)

    def test_equivalencia_ventana_dia_y_periodo_en_todos_los_anios_y_niveles(self):
        niveles = [None, *NIVELES]
        cambios = self.con.total_changes
        for anio in (2024, 2025, 2026):
            dia = datetime(anio, 6, 11)
            intervalos = [(self.inicio.replace(year=anio), self.fin.replace(year=anio)),
                          (dia, dia + timedelta(days=1)), (dia, dia + timedelta(days=2))]
            for inicio, fin in intervalos:
                with self.subTest(anio=anio, inicio=inicio, fin=fin):
                    self.assertEqual(self.contar(inicio, fin, niveles),
                                     conteos_originales(self.con, inicio, fin, niveles))
        self.assertEqual(self.con.total_changes, cambios)

    def test_conteos_distintos_no_suman_zonas_ni_mac_y_excluyen_huerfanos(self):
        conteos = self.contar()
        self.assertEqual(conteos[None], {"NACIONAL": (3, 3, 3, 4)})
        self.assertEqual(conteos["ENTIDAD_FEDERATIVA"], {
            "CDMX": (2, 2, 2, 3), "JALISCO": (1, 1, 1, 1),
            "NO IDENTIFICADA": (1, 1, 1, 1)})
        self.assertEqual(conteos["HUB_CM"], {
            "H1": (2, 2, 2, 3), "H2": (1, 1, 1, 1), "H3": (1, 1, 1, 1),
            "NO IDENTIFICADA": (1, 1, 1, 1)})
        self.assertEqual(conteos["PLAZA"], {
            "P1": (2, 2, 2, 3), "P2": (1, 1, 1, 1), "P3": (1, 1, 1, 1),
            "NO IDENTIFICADA": (1, 1, 1, 1)})
        self.assertGreater(sum(c[0] for c in conteos["HUB_CM"].values()),
                           conteos[None]["NACIONAL"][0])

    def test_agregar_filas_repetidas_no_cambia_ninguna_metrica(self):
        antes = self.contar(niveles=[None, *NIVELES])
        self.con.execute("""INSERT INTO afectados
            SELECT 'duplicado-' || id, incidencia, cliente, mac, region_id, fecha_mx
            FROM afectados""")
        self.assertEqual(self.contar(niveles=[None, *NIVELES]), antes)

    def test_periodo_deduplica_clientes_y_mac_entre_dias(self):
        dia = datetime(2026, 6, 11)
        total = self.contar(dia, dia + timedelta(days=2))[None]["NACIONAL"]
        self.assertEqual(total, (5, 6, 5, 7))
        diarios = [self.contar(dia + timedelta(days=n), dia + timedelta(days=n+1))
                   [None]["NACIONAL"] for n in range(2)]
        self.assertGreater(sum(c[0] for c in diarios), total[0])
        self.assertGreater(sum(c[2] for c in diarios), total[2])

    def test_pares_cliente_incidencia_no_colisionan_al_concatenar(self):
        self.con.executemany("INSERT INTO incidencias VALUES (?, ?)", [("23", ""), ("3", "")])
        self.con.executemany("INSERT INTO afectados VALUES (?, ?, ?, ?, ?, ?)", [
            ("par1", "23", "1", None, "r1", "2026-06-11 13:00:00"),
            ("par2", "3", "12", None, "r1", "2026-06-11 13:00:00"),
        ])
        self.assertEqual(self.contar()[None]["NACIONAL"], (5, 5, 3, 6))

    def test_intervalos_vacios_conservan_diccionarios_vacios(self):
        for inicio, fin in [(self.fin, self.fin), (self.fin, self.inicio),
                            (datetime(2023, 6, 11), datetime(2023, 6, 12))]:
            with self.subTest(inicio=inicio, fin=fin):
                esperado = {nivel: {} for nivel in NIVELES_ANALISIS}
                self.assertEqual(self.contar(inicio, fin), esperado)
                self.assertEqual(conteos_originales(self.con, inicio, fin, NIVELES_ANALISIS), esperado)

    def test_niveles_parciales_repetidos_y_vacios(self):
        self.assertEqual(self.contar(niveles=[]), {})
        for niveles in ([None], ["HUB_CM"], ["PLAZA", None, "PLAZA"]):
            with self.subTest(niveles=niveles):
                self.assertEqual(self.contar(niveles=niveles),
                                 conteos_originales(self.con, self.inicio, self.fin, niveles))

    def test_nombre_nacional_como_zona_no_mezcla_niveles(self):
        self.con.execute("UPDATE regiones SET ENTIDAD_FEDERATIVA='NACIONAL', HUB_CM='NACIONAL', "
                         "PLAZA='NACIONAL' WHERE id='r3'")
        conteos = self.contar()
        self.assertEqual(conteos[None]["NACIONAL"], (3, 3, 3, 4))
        for nivel in NIVELES_ANALISIS[1:]:
            self.assertEqual(conteos[nivel]["NACIONAL"], (1, 1, 1, 1))

    def test_todos_los_niveles_se_calculan_con_una_sola_consulta(self):
        consultas = []
        self.con.set_trace_callback(consultas.append)
        self.contar()
        self.assertEqual(len(consultas), 1)
        plan = [r[3] for r in self.con.execute("EXPLAIN QUERY PLAN " + consultas[0])]
        # Una selección de afectados y un acceso a cada catálogo, antes de agrupar.
        for alias in ("a", "d", "i"):
            accesos = [p for p in plan if p.startswith((f"SEARCH {alias} ", f"SCAN {alias}"))]
            self.assertEqual(len(accesos), 1, plan)

    def test_nivel_invalido_se_rechaza_antes_de_ejecutar_sql(self):
        consultas = []
        self.con.set_trace_callback(consultas.append)
        with self.assertRaisesRegex(ValueError, "Nivel geográfico no soportado"):
            self.contar(niveles=[None, "PLAZA); DROP TABLE afectados; --"])
        self.assertEqual(consultas, [])

    def preparar_analisis(self):
        conf = {"inicio_analisis": "2026-06-11", "fin_analisis": "2026-06-12",
                "anios_comparacion": [2024, 2025],
                "niveles_geograficos": NIVELES_ANALISIS[1:],
                "minutos_antes": 30, "minutos_despues": 180,
                "minimo_ventanas_comparables": 2, "k_vecinos_distancia": 1,
                "minimo_clientes_anomalia": 2, "minimo_exceso_clientes": 2,
                "minimo_puntuacion_distancia": 0}
        partidos = [{"PARTIDO_ID": str(n), "PARTIDO": f"Partido {n}",
                     "inicio": datetime(2026, 6, 11, hora)}
                    for n, hora in enumerate((13, 13, 14), 1)]
        dias = {f"{anio}-06-{dia}" for anio in (2024, 2025, 2026) for dia in (11, 12)}
        self.con.executemany("INSERT INTO afectados VALUES (?, ?, ?, ?, ?, ?)",
            [(f"extra-{n}", "2026-i2", f"extra-c{n}", f"extra-m{n}", "r1",
              "2026-06-11 13:00:00") for n in range(20)])
        return conf, partidos, dias

    def test_analizar_conserva_todas_las_salidas_y_no_duplica_filas(self):
        conf, partidos, dias = self.preparar_analisis()
        for ausente in (None, "2025-06-11", "2026-06-11"):
            presentes = dias - {ausente}
            with self.subTest(dia_ausente=ausente), TemporaryDirectory() as temporal:
                salida_original, salida_nueva = Path(temporal) / "original", Path(temporal) / "nueva"
                salida_original.mkdir()
                salida_nueva.mkdir()
                with redirect_stdout(StringIO()), patch(
                        "src.analisis.cuenta_intervalo_todos", side_effect=conteos_originales):
                    original = analizar(self.con, conf, partidos, salida_original, presentes)
                with redirect_stdout(StringIO()):
                    nuevo = analizar(self.con, conf, partidos, salida_nueva, presentes)
                self.assertEqual(nuevo, original)
                self.assertEqual({p.name for p in salida_nueva.iterdir()},
                                 {p.name for p in salida_original.iterdir()})
                for archivo in salida_original.iterdir():
                    self.assertEqual((salida_nueva / archivo.name).read_bytes(), archivo.read_bytes(),
                                     archivo.name)
                for nombre, claves in (
                        ("comparacion_por_partido_zona.csv", ("PARTIDO_ID", "NIVEL", "ZONA")),
                        ("comparacion_diaria_zona.csv", ("FECHA_MX", "NIVEL", "ZONA")),
                        ("comparacion_periodo_zona.csv", ("NIVEL", "ZONA")),
                        ("detalle_clientes_alertados.csv", ("PARTIDO_ID", "WIDMT_INCIDENCIA_REMEDY_CLIENTE")),
                        ("fallas_generales_por_cliente.csv", ("WIDMT_CLIENTE",))):
                    with (salida_nueva / nombre).open(encoding="utf-8-sig", newline="") as f:
                        filas = list(csv.DictReader(f))
                    ids = [tuple(fila[k] for k in claves) for fila in filas]
                    self.assertEqual(len(ids), len(set(ids)), nombre)
                if ausente is None:
                    self.assertGreater(nuevo["alertas"], 0)
                    self.assertGreater(nuevo["filas_detalle_alertas"], 0)

    def test_comparar_intervalos_consulta_una_vez_por_anio_cubierto(self):
        intervalos = {a: (self.inicio.replace(year=a), self.fin.replace(year=a))
                      for a in (2024, 2025, 2026)}
        for dias, esperado in [({f"{a}-06-11" for a in intervalos}, 3),
                               ({"2024-06-11", "2026-06-11"}, 2), (set(), 0)]:
            with self.subTest(dias=dias), patch(
                    "src.analisis.cuenta_intervalo_todos", wraps=cuenta_intervalo_todos) as contar:
                filas = list(comparar_intervalos(self.con, intervalos, 2026, NIVELES_ANALISIS, dias))
                self.assertEqual(contar.call_count, esperado)
                self.assertEqual(len({(f["NIVEL"], f["ZONA"]) for f in filas}), len(filas))
                if not dias:
                    self.assertEqual(len(filas), 1)
                    self.assertEqual(filas[0]["CLIENTES_DISTINTOS"], "")
                    self.assertFalse(filas[0]["COBERTURA_COMPLETA"])

    def test_cache_reutiliza_intervalos_para_partidos_simultaneos(self):
        conf, partidos, dias = self.preparar_analisis()
        with TemporaryDirectory() as temporal, redirect_stdout(StringIO()), patch(
                "src.analisis.cuenta_intervalo_todos", wraps=cuenta_intervalo_todos) as contar, patch(
                "src.analisis.cuenta_ventana", side_effect=AssertionError("Consulta antigua en el flujo")):
            analizar(self.con, conf, partidos, Path(temporal), dias)
        # 2 horarios * 3 años + 2 días * 3 años + 1 periodo * 3 años.
        self.assertEqual(contar.call_count, 15)
        intervalos = [(c.args[1], c.args[2]) for c in contar.call_args_list]
        self.assertEqual(len(intervalos), len(set(intervalos)))
        for llamada in contar.call_args_list:
            self.assertEqual(llamada.args[3], NIVELES_ANALISIS)

    def test_cache_evaluaciones_conserva_resultados_de_partidos_independientes(self):
        conf, partidos, dias = self.preparar_analisis()
        # Los horarios repetidos no tienen que aparecer consecutivamente.
        partidos = [partidos[0], partidos[2], partidos[1]]
        partidos[0].update(JUEGA_MEXICO="SI", SEDE_EN_MEXICO="SI", SEDE="Sede A")
        partidos[2].update(JUEGA_MEXICO="NO", SEDE_EN_MEXICO="NO", SEDE="Sede B")
        archivos_partido = ("anomalias_por_partido_zona.csv", "comparacion_por_partido_zona.csv",
                            "alertas_ordenadas.csv", "detalle_clientes_alertados.csv")

        def leer_filas(ruta):
            with ruta.open(encoding="utf-8-sig", newline="") as fichero:
                return list(csv.DictReader(fichero))

        for ausente, minimo in ((None, 2), ("2025-06-11", 2), ("2026-06-11", 2), (None, 6)):
            with self.subTest(dia_ausente=ausente, minimo=minimo), TemporaryDirectory() as temporal:
                configuracion = {**conf, "minimo_ventanas_comparables": minimo}
                presentes = dias - {ausente}
                combinada = Path(temporal) / "combinada"
                combinada.mkdir()
                with redirect_stdout(StringIO()), patch("src.analisis.evaluar", wraps=evaluar) as evaluar_mock:
                    resumen = analizar(self.con, configuracion, partidos, combinada, presentes)
                filas = leer_filas(combinada / "comparacion_por_partido_zona.csv")
                # Una evaluación por zona de cada horario, aunque haya varios partidos.
                esperadas = sum(f["PARTIDO_ID"] in ("1", "3") for f in filas)
                self.assertEqual(evaluar_mock.call_count, esperadas)
                self.assertLess(evaluar_mock.call_count, len(filas))

                independientes = {nombre: [] for nombre in archivos_partido}
                resumenes = []
                for partido in partidos:
                    salida = Path(temporal) / partido["PARTIDO_ID"]
                    salida.mkdir()
                    with redirect_stdout(StringIO()):
                        resumenes.append(analizar(self.con, configuracion, [partido], salida, presentes))
                    for archivo in salida.iterdir():
                        if archivo.name in independientes:
                            independientes[archivo.name].extend(leer_filas(archivo))
                        else:
                            self.assertEqual(archivo.read_bytes(), (combinada / archivo.name).read_bytes(),
                                             archivo.name)
                for nombre, originales in independientes.items():
                    self.assertCountEqual(leer_filas(combinada / nombre), originales, nombre)
                for campo in ("partidos", "filas_metricas", "alertas", "filas_sin_base",
                              "filas_detalle_alertas"):
                    self.assertEqual(resumen[campo], sum(r[campo] for r in resumenes), campo)

    def test_avance_muestra_ultimo_partido_y_las_etapas_historicas(self):
        conf, partidos, dias = self.preparar_analisis()
        for total in (1, 20, 104):
            calendario = [{**partidos[0], "PARTIDO_ID": str(n), "PARTIDO": f"Partido {n}"}
                          for n in range(1, total+1)]
            consola = StringIO()
            with self.subTest(total=total), TemporaryDirectory() as temporal, redirect_stdout(consola):
                analizar(self.con, conf, calendario, Path(temporal), dias)
            avances = [*range(20, total+1, 20)]
            if not avances or avances[-1] != total:
                avances.append(total)
            self.assertEqual(consola.getvalue().splitlines(), [
                *(f"Partidos analizados: {n}/{total}" for n in avances),
                "Comparando días y periodo completo con el histórico...",
                "Periodo completo comparado. Iniciando comparación diaria (2 días)...",
                "Días comparados: 2/2",
                "Exportando fallas generales por cliente...",
            ])


if __name__ == "__main__":
    unittest.main()
