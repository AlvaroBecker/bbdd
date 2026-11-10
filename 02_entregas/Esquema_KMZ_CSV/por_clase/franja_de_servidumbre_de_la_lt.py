"""Creacion de la clase franja_de_servidumbre_de_la_lt."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'franja_de_servidumbre_de_la_lt']+sys.argv[1:])
