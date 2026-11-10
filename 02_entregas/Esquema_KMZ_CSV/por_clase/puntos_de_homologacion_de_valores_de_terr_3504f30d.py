"""Creacion de la clase puntos_de_homologacion_de_valores_de_terr_3504f30d."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'puntos_de_homologacion_de_valores_de_terr_3504f30d']+sys.argv[1:])
