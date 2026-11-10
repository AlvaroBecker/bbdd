"""Creacion de la clase para_identificar_las_unidades_de_uso_actu_0d06ed96."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'para_identificar_las_unidades_de_uso_actu_0d06ed96']+sys.argv[1:])
