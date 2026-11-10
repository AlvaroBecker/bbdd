"""Creacion de la clase elementos_de_la_red_hidrografica_de_la_ca_d30d96e4."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'elementos_de_la_red_hidrografica_de_la_ca_d30d96e4']+sys.argv[1:])
