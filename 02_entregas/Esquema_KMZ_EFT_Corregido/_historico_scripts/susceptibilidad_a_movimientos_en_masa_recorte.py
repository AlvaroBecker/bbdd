import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__=="__main__":
    main(["--clase",'susceptibilidad_a_movimientos_en_masa_recorte']+sys.argv[1:])
