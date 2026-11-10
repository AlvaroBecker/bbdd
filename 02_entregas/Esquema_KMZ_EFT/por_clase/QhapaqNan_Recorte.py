"""Definicion ArcGIS: Datos_Proyecto/QhapaqNan_Recorte."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crear_esquema import main

if __name__ == "__main__":
    main(["--clase", 'QhapaqNan_Recorte'] + sys.argv[1:])
