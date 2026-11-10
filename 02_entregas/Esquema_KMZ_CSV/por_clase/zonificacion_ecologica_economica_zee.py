"""Creacion de la clase zonificacion_ecologica_economica_zee."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'zonificacion_ecologica_economica_zee']+sys.argv[1:])
