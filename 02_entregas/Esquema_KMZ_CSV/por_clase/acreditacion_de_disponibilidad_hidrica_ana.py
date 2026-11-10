"""Creacion de la clase acreditacion_de_disponibilidad_hidrica_ana."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'acreditacion_de_disponibilidad_hidrica_ana']+sys.argv[1:])
