"""Creacion de la clase mapa_de_capacidad_de_uso_mayor_de_la_regi_fd2f6751."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'mapa_de_capacidad_de_uso_mayor_de_la_regi_fd2f6751']+sys.argv[1:])
