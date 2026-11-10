"""Creacion de la clase informacion_del_catastro_minero_la_inform_598b689e."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'informacion_del_catastro_minero_la_inform_598b689e']+sys.argv[1:])
