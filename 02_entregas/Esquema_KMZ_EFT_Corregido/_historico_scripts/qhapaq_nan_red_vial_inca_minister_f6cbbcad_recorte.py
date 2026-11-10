import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__=="__main__":
    main(["--clase",'qhapaq_nan_red_vial_inca_minister_f6cbbcad_recorte']+sys.argv[1:])
