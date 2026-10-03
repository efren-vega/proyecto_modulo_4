"""Pruebas sintéticas de las fuentes filtradas y las fallas por cliente."""

import csv
from contextlib import closing, redirect_stdout
from datetime import datetime, timezone
from io import StringIO
import json
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.analisis import (ARCHIVOS_IR, ARCHIVOS_IRC, cargar_irc,
                          crear_base, descubrir_fuentes_filtradas, ejecutar,
                          fechas_comparables, filas_csv, limites_carga)


def escribir(path, columnas, filas):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="|")
        w.writerow(columnas)
        w.writerows(filas)


def resultado(base, nombre):
    with (base / "resultados" / nombre).open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def preparar(base):
    datos = base / "filtrado"
    generales, clientes = datos / "fallas_generales", datos / "fallas_clientes"
    generales.mkdir(parents=True)
    clientes.mkdir()
    escribir(base / "dim.csv",
             ["WIDDIM_REGION", "REGION", "SUBREGION", "ENTIDAD_FEDERATIVA", "HUB_CM", "PLAZA"],
             [["10", "METRO", "METROPOLITANA", "CDMX", "TLALPAN", "TLALPAN"],
              ["20", "METRO", "METROPOLITANA", "CDMX", "COYOACAN", "COYOACAN"]])
    escribir(base / "partidos.csv", ["PARTIDO_ID", "FECHA_MX", "HORA_INICIO_MX", "PARTIDO"],
             [["1", "2026-06-11", "13:00", "Partido de prueba"]])
    irc = []
    for anio in (2024, 2025, 2026):
        ir = []
        for dia in (11, 12):
            local = datetime(anio, 6, dia, 13)
            utc = local.replace(tzinfo=ZoneInfo("America/Mexico_City")).astimezone(timezone.utc)
            incidencia = f"IR_{anio}_{dia}"
            ir.append([incidencia, local.isoformat(sep=" ")])
            n = 3 if anio == 2026 and dia == 11 else 1
            for c in range(n):
                for mac in range(2):
                    irc.append([f"{incidencia}_{c}_{mac}", incidencia, f"C_{c}", "10",
                                f"MAC_{c}_{mac}", utc.isoformat(sep=" ")])
            if anio == 2026 and dia == 11:
                # Mismo cliente/incidencia en otro hub: el total nacional sigue siendo único.
                irc.append(["otra_region", incidencia, "C_0", "20", "MAC_0_0", utc.isoformat(sep=" ")])
                ir.append(["IR_EXTRA", local.isoformat(sep=" ")])
                for mac in range(2):
                    irc.append([f"extra_{mac}", "IR_EXTRA", "C_0", "10", f"MAC_0_{mac}", utc.isoformat(sep=" ")])
                irc.append(["sin_general", "HUERFANA", "C_HUERFANO", "10", "MAC_H", utc.isoformat(sep=" ")])
        escribir(generales / f"Dataset_Fallas_Generales_Historia_{anio}.csv", ARCHIVOS_IR, ir)
    for n in range(1, 65):
        escribir(clientes / f"remedy_fallas_clientes_filtro_{n}.csv", ARCHIVOS_IRC,
                 irc if n == 1 else irc[:1] if n == 64 else [])
    conf = {"carpeta_datos": "filtrado", "modo_fuentes": "filtrado", "partes_irc_esperadas": 64,
            "dimension_region": "dim.csv", "calendario": "partidos.csv", "partidos_esperados": 1,
            "carpeta_resultados": "resultados", "inicio_analisis": "2026-06-11",
            "fin_analisis": "2026-06-12", "anios_comparacion": [2024, 2025],
            "niveles_geograficos": ["HUB_CM"], "minutos_antes": 30, "minutos_despues": 180,
            "minimo_ventanas_comparables": 6, "k_vecinos_distancia": 3,
            "minimo_clientes_anomalia": 10, "minimo_exceso_clientes": 10,
            "minimo_puntuacion_distancia": 3.0, "exigir_dias_completos": True}
    config = base / "config.json"
    config.write_text(json.dumps(conf), encoding="utf-8")
    return conf, config


class ComparacionHistorica(unittest.TestCase):
    def test_prepara_descarga_antes_de_analizar_si_esta_habilitada(self):
        with TemporaryDirectory() as temporal:
            base = Path(temporal)
            conf, config = preparar(base)
            conf["descargar_datos"] = True
            config.write_text(json.dumps(conf), encoding="utf-8")
            with patch("src.descarga.preparar_datos") as descarga, redirect_stdout(StringIO()):
                resumen = ejecutar(config)
            descarga.assert_called_once_with(config)
            self.assertEqual(resumen["clientes_comparados"], 3)

    def test_descubre_solo_64_fragmentos_filtrados_y_tres_anios(self):
        with TemporaryDirectory() as temporal:
            base = Path(temporal)
            preparar(base)
            carpeta = base / "filtrado"
            ir, irc = descubrir_fuentes_filtradas(carpeta, 64, [2024, 2025, 2026])
            self.assertEqual(len(ir), 3)
            self.assertEqual(len(irc), 64)
            self.assertEqual(irc[1].name, "remedy_fallas_clientes_filtro_2.csv")
            (carpeta / "fallas_clientes" / "remedy_fallas_clientes_filtro_42.csv").unlink()
            with self.assertRaisesRegex(ValueError, r"faltan \[42\]"):
                descubrir_fuentes_filtradas(carpeta, 64, [2024, 2025, 2026])
            with self.assertRaisesRegex(ValueError, r"faltan \[2023\]"):
                descubrir_fuentes_filtradas(carpeta, 64, [2023, 2024, 2025, 2026])

    def test_integracion_compara_anios_deduplica_y_excluye_huerfanas(self):
        with TemporaryDirectory() as temporal:
            base = Path(temporal)
            _, config = preparar(base)
            abiertos = []
            def solo_filtrados(ruta, delimitador=None):
                abiertos.append(ruta)
                if ruta.name not in ("dim.csv", "partidos.csv"):
                    self.assertIn("filtrado", ruta.parts)
                return filas_csv(ruta, delimitador)
            with patch("src.analisis.filas_csv", side_effect=solo_filtrados), redirect_stdout(StringIO()):
                resumen = ejecutar(config)
            self.assertEqual(len(abiertos), 69)
            self.assertEqual(resumen["alertas"], 0)
            self.assertEqual(resumen["clientes_comparados"], 3)
            nacional = next(x for x in resultado(base, "comparacion_por_partido_zona.csv") if x["NIVEL"] == "NACIONAL")
            for campo, valor in {"CLIENTES_DISTINTOS": "3", "MAC_DISTINTAS": "6", "FALLAS_CLIENTE": "4",
                                 "INCIDENCIAS_DISTINTAS": "2", "CLIENTES_DISTINTOS_2024": "1",
                                 "CLIENTES_DISTINTOS_2025": "1", "N_REFERENCIAS": "2", "ESTADO": "SIN_BASE"}.items():
                self.assertEqual(nacional[campo], valor)
            self.assertEqual(float(nacional["VAR_CLIENTES_DISTINTOS_PCT_VS_2024"]), 200)
            periodo = next(x for x in resultado(base, "comparacion_periodo_zona.csv") if x["NIVEL"] == "NACIONAL")
            self.assertEqual(periodo["CLIENTES_DISTINTOS"], "3")  # No suma los conteos diarios.
            self.assertEqual(periodo["FALLAS_CLIENTE"], "5")
            self.assertEqual(periodo["INCIDENCIAS_DISTINTAS"], "3")
            clientes = resultado(base, "fallas_generales_por_cliente.csv")
            c0 = next(x for x in clientes if x["WIDMT_CLIENTE"] == "C_0")
            self.assertEqual(c0["FALLAS_2026"], "3")
            self.assertEqual(c0["FALLAS_2024"], "2")
            self.assertEqual(float(c0["VAR_FALLAS_PCT_VS_HISTORICO"]), 50)
            self.assertEqual(c0["DIF_FALLAS_VS_2024"], "1")
            self.assertEqual(float(c0["VAR_FALLAS_PCT_VS_2025"]), 50)
            nuevo = next(x for x in clientes if x["WIDMT_CLIENTE"] == "C_1")
            self.assertEqual(nuevo["FALLAS_2024"], "0")
            self.assertEqual(nuevo["VAR_FALLAS_PCT_VS_HISTORICO"], "")
            calidad = json.loads((base / "resultados/control_calidad.json").read_text(encoding="utf-8"))
            self.assertEqual(calidad["incidencias_irc_sin_mt_ir"], 1)
            self.assertEqual(calidad["dias_analisis_sin_registros"], [])
            diarias = [x for x in resultado(base, "comparacion_diaria_zona.csv") if x["NIVEL"] == "NACIONAL"]
            self.assertEqual([x["CLIENTES_DISTINTOS"] for x in diarias], ["3", "1"])
            self.assertEqual([x["FALLAS_CLIENTE"] for x in diarias], ["4", "1"])

    def test_historico_incompleto_no_se_interpreta_como_cero(self):
        with TemporaryDirectory() as temporal:
            base = Path(temporal)
            conf, config = preparar(base)
            escribir(base / "filtrado/fallas_generales/Dataset_Fallas_Generales_Historia_2025.csv", ARCHIVOS_IR, [])
            with redirect_stdout(StringIO()), self.assertRaisesRegex(ValueError, "Faltan días"):
                ejecutar(config)
            conf["exigir_dias_completos"] = False
            config.write_text(json.dumps(conf), encoding="utf-8")
            with redirect_stdout(StringIO()):
                ejecutar(config)
            nacional = next(x for x in resultado(base, "comparacion_por_partido_zona.csv") if x["NIVEL"] == "NACIONAL")
            self.assertEqual(nacional["CLIENTES_DISTINTOS_2025"], "")
            self.assertEqual(nacional["PROMEDIO_HISTORICO_CLIENTES_DISTINTOS"], "")
            self.assertEqual(nacional["ANIOS_HISTORICOS_DISPONIBLES"], "2024")
            self.assertEqual(nacional["N_REFERENCIAS"], "1")
            self.assertEqual(resultado(base, "fallas_generales_por_cliente.csv")[0]["FALLAS_2025"], "")

    def test_fechas_exactas_y_limites_por_anio_con_conversion_utc(self):
        inicio = datetime(2026, 6, 11, 0, 10)
        self.assertEqual(fechas_comparables(inicio, [2024, 2025]),
                         [datetime(2024, 6, 11, 0, 10), datetime(2025, 6, 11, 0, 10)])
        conf = {"inicio_analisis": "2026-06-11", "fin_analisis": "2026-07-19",
                "anios_comparacion": [2024, 2025], "minutos_antes": 30, "minutos_despues": 180}
        rangos = limites_carga(conf, [{"inicio": inicio}])
        self.assertEqual(rangos[0][0], datetime(2024, 6, 10, 23, 40))
        self.assertEqual(rangos[0][1], datetime(2024, 7, 20))
        with TemporaryDirectory() as temporal, closing(sqlite3.connect(":memory:")) as con:
            p = Path(temporal) / "filtrado.csv"
            filas = [[str(n), "IR", "C", "10", "MAC", fecha] for n, fecha in enumerate(
                ["2024-06-11 05:39:59", "2024-06-11 05:40:00", "2025-06-11 06:00:00",
                 "2026-07-20 05:59:59", "2026-07-20 06:00:00", "2025-08-11 19:00:00"])]
            escribir(p, ARCHIVOS_IRC, filas)
            crear_base(con)
            with redirect_stdout(StringIO()):
                info = cargar_irc(con, [p], rangos)
            self.assertEqual(info["filas_en_periodo"], 3)
            self.assertEqual(info["filas_fuera_periodo"], 3)

    def test_modos_anteriores_rechazados_antes_de_leer_fuentes(self):
        with TemporaryDirectory() as temporal:
            base = Path(temporal)
            conf, config = preparar(base)
            conf["modo_fuentes"] = "historico"
            config.write_text(json.dumps(conf), encoding="utf-8")
            with patch("src.analisis.filas_csv") as leer, self.assertRaisesRegex(ValueError, "no se leerán fuentes originales"):
                ejecutar(config)
            leer.assert_not_called()


if __name__ == "__main__":
    unittest.main()
