"""Creacion de la clase red_de_sitios_que_son_importantes_para_la_2d3e065b."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from crear_esquema import main
if __name__ == "__main__":
    main(["--clase",'red_de_sitios_que_son_importantes_para_la_2d3e065b']+sys.argv[1:])
