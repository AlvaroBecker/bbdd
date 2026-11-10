"""Creacion de la clase acceso_existente_trocha_carrozable."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'acceso_existente_trocha_carrozable']+sys.argv[1:])
