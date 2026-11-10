"""Creacion de la clase redes_de_distribucion_en_media_tension_punto."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'redes_de_distribucion_en_media_tension_punto']+sys.argv[1:])
