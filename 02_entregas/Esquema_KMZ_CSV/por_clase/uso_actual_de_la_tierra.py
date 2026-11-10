"""Creacion de la clase uso_actual_de_la_tierra."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'uso_actual_de_la_tierra']+sys.argv[1:])
