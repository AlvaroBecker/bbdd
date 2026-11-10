"""Creacion de la clase distancias_buffers_a_areas_de_interes."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'distancias_buffers_a_areas_de_interes']+sys.argv[1:])
