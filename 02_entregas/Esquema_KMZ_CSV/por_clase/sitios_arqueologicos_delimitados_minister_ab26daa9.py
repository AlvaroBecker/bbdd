"""Creacion de la clase sitios_arqueologicos_delimitados_minister_ab26daa9."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'sitios_arqueologicos_delimitados_minister_ab26daa9']+sys.argv[1:])
