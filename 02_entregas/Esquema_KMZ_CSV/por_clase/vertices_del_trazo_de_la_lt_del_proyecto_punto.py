"""Creacion de la clase vertices_del_trazo_de_la_lt_del_proyecto_punto."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'vertices_del_trazo_de_la_lt_del_proyecto_punto']+sys.argv[1:])
