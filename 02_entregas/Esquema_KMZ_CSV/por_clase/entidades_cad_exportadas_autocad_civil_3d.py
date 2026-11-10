"""Creacion de la clase entidades_cad_exportadas_autocad_civil_3d."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'entidades_cad_exportadas_autocad_civil_3d']+sys.argv[1:])
