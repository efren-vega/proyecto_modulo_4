"""Descarga las entradas sin ejecutar ni reemplazar los resultados del análisis."""

import argparse
import json
from pathlib import Path
import sys

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from src.descarga import preparar_datos


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=RAIZ / "config.json")
    parser.add_argument("--listar", action="store_true", help="Valida los nombres públicos sin descargar los CSV.")
    args = parser.parse_args()
    try:
        resumen = preparar_datos(args.config, solo_listar=args.listar)
    except (OSError, ValueError, RuntimeError) as exc:
        parser.exit(1, f"Error de descarga: {exc}\n")
    print(json.dumps(resumen, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
