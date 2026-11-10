"""Creacion de la clase areas_reservadas_zonas_urbanas."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'areas_reservadas_zonas_urbanas']+sys.argv[1:])
