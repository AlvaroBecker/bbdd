"""Creacion de la clase lineas_y_geoglifos_de_nasca_patrimonio_unesco."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'lineas_y_geoglifos_de_nasca_patrimonio_unesco']+sys.argv[1:])
