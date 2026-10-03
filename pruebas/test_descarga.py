"""Pruebas de descarga con Google Drive simulado; no transfieren datos reales."""

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from src.descarga import AGENTE_DESCARGA, archivos_esperados, listar_carpeta, preparar_datos


def configurar(base):
    conf = {
        "carpeta_datos": "raw_data", "anios_comparacion": [2024, 2025],
        "inicio_analisis": "2026-06-11", "partes_irc_esperadas": 64,
        "dimension_region": "raw_data/region_y_calendario/Dataset_Dim_Region.csv",
        "calendario": "raw_data/region_y_calendario/calendario_partidos_2026.csv",
        "fuentes_drive": {k: f"https://drive.google.com/drive/folders/{k}"
                          for k in ["region_y_calendario", "fallas_generales", "fallas_clientes"]},
    }
    ruta = base / "config.json"
    ruta.write_text(json.dumps(conf), encoding="utf-8")
    return conf, ruta


def escribir_csv(ruta, campos):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text("|".join(campos) + "\n", encoding="utf-8")


def drive_simulado(conf):
    esperados = archivos_esperados(conf)
    def listar(**kwargs):
        carpeta = Path(kwargs["output"]).name
        return [SimpleNamespace(id=nombre, path=nombre) for nombre in esperados[carpeta]]
    def descargar(**kwargs):
        ruta = Path(kwargs["output"])
        escribir_csv(ruta, esperados[ruta.parent.name][ruta.name])
        return str(ruta)
    return SimpleNamespace(download_folder=Mock(side_effect=listar), download=Mock(side_effect=descargar))


class DescargaDrive(unittest.TestCase):
    def test_descarga_69_archivos_y_reutiliza_sin_red(self):
        with TemporaryDirectory() as temporal:
            base = Path(temporal)
            conf, config = configurar(base)
            drive = drive_simulado(conf)
            with patch.dict("sys.modules", {"gdown": drive}), redirect_stdout(StringIO()):
                resumen = preparar_datos(config)
                self.assertEqual(resumen["descargados"], 69)
                self.assertEqual(drive.download_folder.call_count, 3)
                self.assertEqual(drive.download.call_count, 69)
                drive.download_folder.reset_mock()
                drive.download.reset_mock()
                resumen = preparar_datos(config)
                self.assertEqual(resumen["reutilizados"], 69)
                drive.download_folder.assert_not_called()
                drive.download.assert_not_called()
            self.assertEqual(len(list((base / "raw_data/fallas_clientes").glob("*.csv"))), 64)

    def test_solo_descarga_la_parte_faltante_y_reanuda(self):
        with TemporaryDirectory() as temporal:
            base = Path(temporal)
            conf, config = configurar(base)
            for carpeta, nombres in archivos_esperados(conf).items():
                for nombre, campos in nombres.items():
                    if nombre != "remedy_fallas_clientes_filtro_64.csv":
                        escribir_csv(base / "raw_data" / carpeta / nombre, campos)
            drive = drive_simulado(conf)
            with patch.dict("sys.modules", {"gdown": drive}), redirect_stdout(StringIO()):
                resumen = preparar_datos(config)
            self.assertEqual(resumen["descargados"], 1)
            self.assertEqual(resumen["reutilizados"], 68)
            args = drive.download.call_args.kwargs
            self.assertEqual(args["user_agent"], AGENTE_DESCARGA)
            self.assertTrue(args["resume"])
            self.assertTrue(args["use_cookies"])
            self.assertEqual(Path(args["cookies_file"]), base / "raw_data/.gdown_cookies.txt")
            self.assertEqual(args["retries"], 3)
            self.assertEqual(Path(args["output"]).name, "remedy_fallas_clientes_filtro_64.csv")

    def test_listado_valida_64_partes_sin_descargar(self):
        with TemporaryDirectory() as temporal:
            conf, config = configurar(Path(temporal))
            drive = drive_simulado(conf)
            with patch.dict("sys.modules", {"gdown": drive}), redirect_stdout(StringIO()):
                resumen = preparar_datos(config, solo_listar=True)
            self.assertEqual(len(resumen["carpetas"]["fallas_clientes"]), 64)
            drive.download.assert_not_called()

    def test_rechaza_carpeta_incompleta_antes_de_descargar(self):
        with TemporaryDirectory() as temporal:
            conf, config = configurar(Path(temporal))
            drive = drive_simulado(conf)
            listado = drive.download_folder.side_effect
            drive.download_folder.side_effect = lambda **kw: listado(**kw)[:-1]
            with patch.dict("sys.modules", {"gdown": drive}), redirect_stdout(StringIO()):
                with self.assertRaisesRegex(ValueError, "faltan"):
                    preparar_datos(config)
            drive.download.assert_not_called()

    def test_rechaza_duplicados_y_rutas_remotas_inesperadas(self):
        esperados = {"datos.csv": ("CAMPO",)}
        for paths in [["datos.csv", "datos.csv"], ["../datos.csv"]]:
            with self.subTest(paths=paths):
                drive = SimpleNamespace(download_folder=Mock(return_value=[
                    SimpleNamespace(id=str(i), path=p) for i, p in enumerate(paths)]))
                with self.assertRaises(ValueError):
                    listar_carpeta(drive, "https://drive.google.com/drive/folders/prueba", Path("raw_data"), esperados)

    def test_admite_error_tipografico_del_calendario(self):
        drive = SimpleNamespace(download_folder=Mock(return_value=[
            SimpleNamespace(id="calendario", path="caldenario_partidos_2026.csv")]))
        plan = listar_carpeta(drive, "https://drive.google.com/drive/folders/prueba", Path("raw_data"),
                              {"calendario_partidos_2026.csv": ("PARTIDO_ID",)})
        self.assertEqual(plan[0]["nombre"], "calendario_partidos_2026.csv")

    def test_no_reutiliza_csv_con_encabezado_corrupto(self):
        with TemporaryDirectory() as temporal:
            base = Path(temporal)
            _, config = configurar(base)
            ruta = base / "raw_data/region_y_calendario/Dataset_Dim_Region.csv"
            escribir_csv(ruta, ["HTML", "ERROR"])
            with self.assertRaisesRegex(ValueError, "encabezado"):
                preparar_datos(config)
            self.assertEqual(ruta.read_text(encoding="utf-8"), "HTML|ERROR\n")

    def test_fallo_de_transferencia_no_informa_fuentes_completas(self):
        with TemporaryDirectory() as temporal:
            conf, config = configurar(Path(temporal))
            drive = drive_simulado(conf)
            drive.download.side_effect = OSError("Conexión interrumpida")
            with patch.dict("sys.modules", {"gdown": drive}), redirect_stdout(StringIO()):
                with self.assertRaisesRegex(RuntimeError, "continuar"):
                    preparar_datos(config)

    def test_csv_vacio_se_descarga_de_nuevo(self):
        with TemporaryDirectory() as temporal:
            base = Path(temporal)
            conf, config = configurar(base)
            ruta = base / "raw_data/region_y_calendario/Dataset_Dim_Region.csv"
            ruta.parent.mkdir(parents=True)
            ruta.touch()
            drive = drive_simulado(conf)
            with patch.dict("sys.modules", {"gdown": drive}), redirect_stdout(StringIO()):
                self.assertEqual(preparar_datos(config)["descargados"], 69)
            self.assertGreater(ruta.stat().st_size, 0)

    def test_archivo_bloqueado_no_impide_los_otros_y_se_recupera(self):
        with TemporaryDirectory() as temporal:
            base = Path(temporal)
            conf, config = configurar(base)
            drive = drive_simulado(conf)
            descargar = drive.download.side_effect
            bloqueado = "remedy_fallas_clientes_filtro_34.csv"
            def con_fallo(**kwargs):
                if kwargs["id"] == bloqueado:
                    raise OSError("Archivo temporalmente bloqueado")
                return descargar(**kwargs)
            drive.download.side_effect = con_fallo
            with patch.dict("sys.modules", {"gdown": drive}), redirect_stdout(StringIO()):
                with self.assertRaisesRegex(RuntimeError, "1 descargas pendientes"):
                    preparar_datos(config)
                self.assertEqual(len(list((base / "raw_data").rglob("*.csv"))), 68)
                self.assertTrue((base / "raw_data/fallas_clientes/remedy_fallas_clientes_filtro_64.csv").exists())
                drive.download.side_effect = descargar
                drive.download.reset_mock()
                self.assertEqual(preparar_datos(config)["descargados"], 1)
                drive.download.assert_called_once()


if __name__ == "__main__":
    unittest.main()
