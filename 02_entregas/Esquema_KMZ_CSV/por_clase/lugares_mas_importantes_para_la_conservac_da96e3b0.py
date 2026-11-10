"""Creacion de la clase lugares_mas_importantes_para_la_conservac_da96e3b0."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'lugares_mas_importantes_para_la_conservac_da96e3b0']+sys.argv[1:])
