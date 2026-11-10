"""Creacion de la clase areas_clave_para_la_biodiversidad_kba."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'areas_clave_para_la_biodiversidad_kba']+sys.argv[1:])
