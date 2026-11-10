"""Creacion de la clase areas_importantes_para_las_aves_iba."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'areas_importantes_para_las_aves_iba']+sys.argv[1:])
