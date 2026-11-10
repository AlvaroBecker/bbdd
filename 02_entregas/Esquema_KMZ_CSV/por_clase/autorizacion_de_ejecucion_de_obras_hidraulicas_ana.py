"""Creacion de la clase autorizacion_de_ejecucion_de_obras_hidraulicas_ana."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'autorizacion_de_ejecucion_de_obras_hidraulicas_ana']+sys.argv[1:])
