"""Creacion de la clase trazo_alternativas_de_ruta_de_la_lt_punto."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'trazo_alternativas_de_ruta_de_la_lt_punto']+sys.argv[1:])
