"""Definicion ArcGIS: Datos_Proyecto/Muestreo."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crear_esquema import main

if __name__ == "__main__":
    main(["--clase", 'Muestreo'] + sys.argv[1:])
