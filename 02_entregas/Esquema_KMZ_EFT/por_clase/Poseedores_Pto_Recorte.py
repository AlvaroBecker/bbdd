"""Definicion ArcGIS: Datos_Proyecto/Poseedores_Pto_Recorte."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from crear_esquema import main

if __name__ == "__main__":
    main(["--clase", 'Poseedores_Pto_Recorte'] + sys.argv[1:])
