"""Creacion de la clase restricciones_aeronauticas_pista_60c6d71f_poligono."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'restricciones_aeronauticas_pista_60c6d71f_poligono']+sys.argv[1:])
