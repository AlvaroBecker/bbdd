"""Creacion de la clase formalizacion_de_derechos_de_uso_de_agua_ana."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'formalizacion_de_derechos_de_uso_de_agua_ana']+sys.argv[1:])
