"""Creacion de la clase hidrocarburos_lotes_ductos_pozos_poligono."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'hidrocarburos_lotes_ductos_pozos_poligono']+sys.argv[1:])
