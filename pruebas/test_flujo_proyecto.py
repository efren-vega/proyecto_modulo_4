"""Ejecuto el flujo vigente sin archivos históricos ni informes precalculados."""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

from src.analisis import ARCHIVOS_IR, ARCHIVOS_IRC
from proyecto.revision import revisar_clientes

RAIZ = Path(__file__).resolve().parents[1]


def escribir(ruta, columnas, filas):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo, delimiter="|")
        escritor.writerow(columnas)
        escritor.writerows(filas)


def preparar(base, abundantes=True):
    for nombre in (
        "main.py", "requirements.txt", "src/__init__.py", "src/analisis.py", "src/descarga.py",
        "scripts/__init__.py", "scripts/descargar_datos.py", "proyecto/__init__.py", "proyecto/eda.py",
        "proyecto/revision.py", "proyecto/validar_proyecto.py", "proyecto/proyecto_final_mineria_de_datos.ipynb",
    ):
        destino = base / nombre
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(RAIZ / nombre, destino)
    region = base / "raw_data/region_y_calendario"
    escribir(region / "Dataset_Dim_Region.csv",
             ["WIDDIM_REGION", "REGION", "SUBREGION", "ENTIDAD_FEDERATIVA", "HUB_CM", "PLAZA"],
             [["10", "REGION", "SUBREGION", "ENTIDAD", "HUB", "PLAZA"],
              ["20", "REGION", "SUBREGION", "OTRA", "OTRO HUB", "OTRA PLAZA"]])
    fechas = ["2026-06-11", "2026-06-18", "2026-06-19", "2026-06-24"]
    escribir(region / "calendario_partidos_2026.csv",
             ["PARTIDO_ID", "FECHA_MX", "HORA_INICIO_MX", "PARTIDO"],
             [[str(i), dia, "13:00", f"Partido sintético {i}"] for i, dia in enumerate(fechas, 1)])
    irc = []
    for anio in (2024, 2025, 2026):
        ir = []
        for offset in range(39):
            local = datetime.combine(date(anio, 6, 11)+timedelta(days=offset), datetime.min.time()).replace(hour=13)
            utc = local.replace(tzinfo=ZoneInfo("America/Mexico_City")).astimezone(timezone.utc)
            incidencia = f"IR_{anio}_{offset}"
            ir.append([incidencia, local.isoformat(sep=" ")])
            n = ((25 if offset in (7, 8) else 3+offset % 6) if anio == 2026 else 1+offset % 3) if abundantes else 1
            for c in range(n):
                region_cliente = "20" if abundantes and anio == 2026 and c >= 12 else "10"
                irc.append([f"{anio}_{offset}_{c}", incidencia, f"C_{c:03}", region_cliente,
                            f"MAC_{c:03}", utc.isoformat(sep=" ")])
        escribir(base / f"raw_data/fallas_generales/Dataset_Fallas_Generales_Historia_{anio}.csv", ARCHIVOS_IR, ir)
    for parte in range(1, 65):
        escribir(base / f"raw_data/fallas_clientes/remedy_fallas_clientes_filtro_{parte}.csv", ARCHIVOS_IRC,
                 irc if parte == 1 else [])
    conf = json.loads((RAIZ / "config.json").read_text(encoding="utf-8"))
    conf.update(descargar_datos=False, partidos_esperados=4)
    (base / "config.json").write_text(json.dumps(conf), encoding="utf-8")


class FlujoProyecto(unittest.TestCase):
    def ejecutar_script(self, base, nombre, *args, cwd=None):
        proceso = subprocess.run([sys.executable, str(base / nombre), *args], cwd=cwd or base,
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        self.assertEqual(proceso.returncode, 0, proceso.stdout+proceso.stderr)
        return proceso.stdout

    def test_main_eda_revision_y_validacion_sin_historico(self):
        with TemporaryDirectory() as temporal:
            base = Path(temporal)
            preparar(base)
            self.assertFalse((base / "proyecto/historico").exists())
            self.assertFalse((base / "requisitos").exists())
            for script in ("main.py", "proyecto/eda.py", "proyecto/revision.py"):
                self.ejecutar_script(base, script)
            self.ejecutar_script(base, "proyecto/validar_proyecto.py", "--exigir-resultados")
            resumen = json.loads((base / "proyecto/recursos/resumen_revision.json").read_text(encoding="utf-8"))
            self.assertGreater(resumen["indicadores"]["alertas"], 0)
            self.assertEqual(resumen["verificacion"]["filas_clientes_recalculadas"], 25)
            self.assertEqual(resumen["indicadores"]["clientes"]["afectados_por_anio"]["2026"], 25)
            self.assertEqual(len(resumen["sensibilidad"]), 10)
            self.assertGreater(resumen["indicadores"]["alertas_cero"], 0)
            self.assertTrue((base / "proyecto/recursos/evolucion_clientes_diaria.png").is_file())
            self.assertFalse((base / "resultados/interpretacion").exists())
            # Ejecuto las trece celdas de una copia, usando sólo el kernel de este entorno.
            import nbformat
            from nbclient import NotebookClient
            from jupyter_client import KernelManager
            from jupyter_client.kernelspec import KernelSpecManager
            notebook = nbformat.read(base / "proyecto/proyecto_final_mineria_de_datos.ipynb", as_version=4)
            kernel_specs = KernelSpecManager(kernel_dirs=[str(Path(sys.prefix) / "share/jupyter/kernels")])
            kernel = KernelManager(kernel_name="python3", kernel_spec_manager=kernel_specs)
            entorno = {"IPYTHONDIR": str(base / "ipython"), "JUPYTER_RUNTIME_DIR": str(base / "jupyter-runtime")}
            with patch.dict(os.environ, entorno):
                cliente = NotebookClient(notebook, km=kernel, timeout=120,
                                         resources={"metadata": {"path": str(base / "proyecto")}})
                try:
                    cliente.execute()
                finally:
                    if cliente.kc is not None:
                        cliente.kc.stop_channels()
                    if kernel.has_kernel:
                        kernel.shutdown_kernel(now=True)
                    kernel.cleanup_resources()
            self.assertEqual(sum(c.cell_type == "code" and c.execution_count is not None for c in notebook.cells), 13)
            # Verifico el descargador movido desde un directorio diferente, reutilizando los 69 archivos.
            salida = self.ejecutar_script(base, "scripts/descargar_datos.py", "--config", str(base / "config.json"), cwd=base.parent)
            self.assertIn('"reutilizados": 69', salida)

    def test_revision_sin_alertas_ni_incremento_no_divide_entre_cero(self):
        with TemporaryDirectory() as temporal:
            base = Path(temporal)
            preparar(base, abundantes=False)
            self.ejecutar_script(base, "main.py")
            self.ejecutar_script(base, "proyecto/revision.py")
            resumen = json.loads((base / "proyecto/recursos/resumen_revision.json").read_text(encoding="utf-8"))
            self.assertEqual(resumen["indicadores"]["alertas"], 0)
            self.assertIsNone(resumen["indicadores"]["porcentaje_alertas_cero"])
            self.assertIsNone(resumen["indicadores"]["participacion_dos_entidades"])

    def test_recurrencia_rechaza_salida_que_no_concilia_con_el_nacional(self):
        with TemporaryDirectory() as temporal:
            base = Path(temporal)
            preparar(base)
            self.ejecutar_script(base, "main.py")
            ruta = base / "resultados/fallas_generales_por_cliente.csv"
            with ruta.open(encoding="utf-8-sig", newline="") as archivo:
                lector = csv.DictReader(archivo)
                campos, filas = lector.fieldnames, list(lector)
            filas[0]["FALLAS_2026"] = "999"
            with ruta.open("w", encoding="utf-8-sig", newline="") as archivo:
                escritor = csv.DictWriter(archivo, fieldnames=campos)
                escritor.writeheader()
                escritor.writerows(filas)
            with (base / "resultados/comparacion_periodo_zona.csv").open(encoding="utf-8-sig", newline="") as archivo:
                nacional = next(f for f in csv.DictReader(archivo) if f["NIVEL"] == "NACIONAL")
            resumen = json.loads((base / "resultados/resumen_ejecucion.json").read_text(encoding="utf-8"))
            with self.assertRaisesRegex(ValueError, "pares del CSV"):
                revisar_clientes(base, nacional, resumen)


if __name__ == "__main__":
    unittest.main()
