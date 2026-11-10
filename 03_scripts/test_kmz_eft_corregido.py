import csv
import json
from pathlib import Path
import unittest

from reglas_kmz_eft_corregido import classify,metadata

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'02_entregas/Esquema_KMZ_EFT_Corregido'


class RulesTests(unittest.TestCase):
    def row(self,d,g,path):return dict(descripcion=d,geometria=g,ruta=path)

    def test_canales_y_conservacion_consolidados(self):
        for d in ['Canales de derivación (ANA)','Canales de riego','Canales de trasvase (ANA)','Canales laterales (ANA)']:
            self.assertEqual(classify(self.row(d,'Línea',''))['base'],'canales')
        for d in ['Áreas de conservación privada (SERNANP)','Áreas de conservación regional (SERNANP)']:
            self.assertEqual(classify(self.row(d,'Polígono',''))['base'],'areas_de_conservacion')

    def test_chanchamayo_misma_descripcion_tres_destinos(self):
        d='Línea de transmisión del proyecto'
        for g,path,target in [('Punto','CHANCHAMAYO / 1. Vértices / LT 138 kV','vertices'),
                              ('Línea','CHANCHAMAYO / 3. Trazo de Ruta / LT 138 kV','mline_td_proyecto_infraestructura'),
                              ('Línea','CHANCHAMAYO / 5. Caminos de Accesos / LT 138 kV','accesos')]:
            self.assertEqual(classify(self.row(d,g,path))['base'],target)

    def test_areas_campo_y_general(self):
        self.assertEqual(classify(self.row('Área de estudio','Polígono','Consultor Ambiental / EBI01A / ÁREA DE ESTUDIO'))['base'],'area_estudio_campo')
        self.assertEqual(classify(self.row('Área de estudio','Polígono','Proyecto / Area de estudio'))['base'],'mline_td_proyecto_area_interes')
        self.assertEqual(classify(self.row('Área de estudio','Línea','SECTORIZACIÓN_AGUAYTIA'))['base'],'')

    def test_alternativa_de_subestacion_no_se_vuelve_trazado(self):
        r=self.row('Trazo / alternativas de ruta de la LT','Polígono','CHANCHAMAYO / 2. Subestaciones / Nueva Campas / 1. Caso Base')
        self.assertEqual(classify(r)['base'],'subestacion')

    def test_pls_mixta_y_cad_no_carga_automatica(self):
        for d,g in [('Line Features','Línea'),('PLS-CADD Project','Línea'),('Conflictos sociales (Defensoría del Pueblo)','Mixta'),('Entidades CAD exportadas (AutoCAD / Civil 3D)','Polígono')]:
            self.assertEqual(classify(self.row(d,g,''))['rol'],'pendiente')

    def test_contexto_sin_inventar_claves(self):
        r=self.row('Acceso nuevo – trocha carrozable','Línea','Proyecto / 1. Ingenieria / LT 220 kV / Alternativa 1 / Accesos Nuevos')
        m=metadata(r)
        self.assertEqual(m['condicion_propuesta'],'Nuevo')
        self.assertEqual(m['componente_propuesto'],'LT 220 kV')
        self.assertEqual(m['alternativa_propuesta'],'Alternativa 1')
        self.assertNotIn('co_proyecto',m)

    def test_condicion_no_crea_otra_clase(self):
        existing=self.row('Subestaciones en operación (OSINERGMIN)','Punto','')
        planned=self.row('Subestaciones proyectadas (OSINERGMIN)','Punto','')
        self.assertEqual(classify(existing)['base'],classify(planned)['base'])
        self.assertEqual(metadata(existing)['condicion_propuesta'],'Existente')
        self.assertEqual(metadata(planned)['condicion_propuesta'],'Proyectado')

    def test_esquema_y_preservacion(self):
        m=json.loads((OUT/'esquema.json').read_text(encoding='utf-8'))
        names={c['nombre'] for c in m['clases']}
        self.assertIn('canales_recorte',names)
        self.assertNotIn('canales_de_trasvase_ana',names)
        self.assertNotIn('linea_de_transmision_del_proyecto_linea',names)
        self.assertIn('mline_td_proyecto_ltransmision',names)
        for c in m['clases']:
            if c['rol']=='recorte':self.assertTrue(c['nombre'].endswith('_recorte'))
        with (OUT/'campos_matriz_a_esquema.csv').open(encoding='utf-8-sig',newline='') as f:r=list(csv.DictReader(f,delimiter=';'))
        self.assertEqual(len({x['fila_matriz'] for x in r}),3507)
        with (OUT/'mapeo_capas_revision.csv').open(encoding='utf-8-sig',newline='') as f:r=list(csv.DictReader(f,delimiter=';'))
        self.assertEqual(sum(int(x['elementos']) for x in r),279623)
        self.assertTrue(all(not x['co_proyecto'] and not x['incluir'] for x in r))


if __name__=='__main__':unittest.main(verbosity=2)
