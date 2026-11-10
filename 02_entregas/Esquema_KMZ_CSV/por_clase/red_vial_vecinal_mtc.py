"""Creacion de la clase red_vial_vecinal_mtc."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'red_vial_vecinal_mtc']+sys.argv[1:])
