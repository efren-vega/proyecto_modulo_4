"""Pruebas del lector y del algoritmo de distancia con datos sintéticos."""

import csv
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from src.analisis import cargar_ir, crear_base, evaluar


def escribir(path, columnas, filas, delim=","):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=delim)
        w.writerow(columnas)
        w.writerows(filas)


class AnomaliasTerritoriales(unittest.TestCase):
    def test_k_vecinos_usa_incidencias_y_mac_ademas_de_clientes(self):
        conf = {"minimo_ventanas_comparables": 6, "k_vecinos_distancia": 3,
                "minimo_clientes_anomalia": 10, "minimo_exceso_clientes": 10,
                "minimo_puntuacion_distancia": 3.0}
        controles = [(100, 1, 100)] * 8
        distinto = evaluar((110, 20, 200), controles, conf)
        self.assertEqual(distinto["ESTADO"], "ANOMALIA")
        self.assertEqual(distinto["K_VECINOS"], 3)
        self.assertGreater(distinto["DISTANCIA_VECINOS"], distinto["P95_DISTANCIA_REFERENCIA"])
        parecido = evaluar((110, 1, 100), controles, conf)
        self.assertEqual(parecido["ESTADO"], "ESPERADO")
        self.assertEqual(evaluar((110, 20, 200), controles[:4], conf)["ESTADO"], "SIN_BASE")

    def test_mt_ir_acepta_campos_largos_en_csv_y_zip(self):
        with TemporaryDirectory() as temporal:
            csv_ir = Path(temporal) / "MT_IR_prueba.csv"
            zip_ir = Path(temporal) / "MT_IR_prueba.zip"
            escribir(csv_ir, ["WIDMT_INCIDENCIA_REMEDY", "FECHA_ENVIO", "DESCRIPCION"],
                    [["IR_LARGA", "2026-06-11 13:00:00", "x" * 200_000]])
            with ZipFile(zip_ir, "w") as archivo:
                archivo.write(csv_ir, arcname="MT_IR_prueba.csv")
            for ruta in (csv_ir, zip_ir):
                with self.subTest(formato=ruta.suffix), closing(sqlite3.connect(":memory:")) as con:
                    crear_base(con)
                    info = cargar_ir(con, [ruta])
                    self.assertEqual(info["filas_leidas"], 1)
                    self.assertEqual(con.execute("SELECT id FROM incidencias").fetchone()[0], "IR_LARGA")



if __name__ == "__main__":
    unittest.main()
