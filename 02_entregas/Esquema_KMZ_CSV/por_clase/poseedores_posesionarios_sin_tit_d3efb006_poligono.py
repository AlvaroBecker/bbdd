"""Creacion de la clase poseedores_posesionarios_sin_tit_d3efb006_poligono."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'poseedores_posesionarios_sin_tit_d3efb006_poligono']+sys.argv[1:])
