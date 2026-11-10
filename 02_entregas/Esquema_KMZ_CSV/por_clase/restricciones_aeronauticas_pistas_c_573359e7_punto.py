"""Creacion de la clase restricciones_aeronauticas_pistas_c_573359e7_punto."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'restricciones_aeronauticas_pistas_c_573359e7_punto']+sys.argv[1:])
