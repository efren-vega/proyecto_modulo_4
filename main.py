"""Ejecuta el análisis territorial de fallas durante el Mundial 2026."""

from pathlib import Path

from src.analisis import ejecutar


# En VS Code: descarga las fuentes públicas faltantes y ejecuta el análisis.
CONFIG = Path(__file__).resolve().parent / "config.json"


if __name__ == "__main__":
    ejecutar(CONFIG)