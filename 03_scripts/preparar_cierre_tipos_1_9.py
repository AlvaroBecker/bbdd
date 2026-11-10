"""Genera el modelo de cierre aprobado; no conecta ni escribe en ArcGIS/SDE."""
from __future__ import annotations

import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '02_entregas/Esquema_KMZ_EFT_Corregido'
BASELINE = OUT.parent / 'Datos_Proyecto_Controlado_v1_8.zip'
sys.path.insert(0, str(OUT))
import referencia_cierre_tipos as ref


def encode(obj):
    return json.dumps(obj, ensure_ascii=False, indent=2).encode('utf-8')


def write(name, data):
    path = OUT / name
    path.write_bytes(data if isinstance(data, bytes) else encode(data))


def csv_update(raw, update):
    stream = io.StringIO(raw.decode('utf-8-sig'), newline='')
    reader = csv.DictReader(stream, delimiter=';')
    rows = list(reader)
    for row in rows:
        update(row)
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=reader.fieldnames, delimiter=';')
    writer.writeheader(); writer.writerows(rows)
    return output.getvalue().encode('utf-8-sig')


def main():
    with zipfile.ZipFile(BASELINE) as archive:
        manifest = json.loads(archive.read('MANIFIESTO_DATOS_PROYECTO.json'))
        assert manifest['version'] == '1.8' and archive.testzip() is None
        for name, expected in manifest['archivos'].items():
            assert ref.sha(archive.read(name)) == expected, name
        baseline_raw = archive.read('esquema.json')
        base = json.loads(baseline_raw)
        assert ref.sha(baseline_raw) == ref.MODEL11_SHA
        assert ref.sha(archive.read('PERFIL_COMPLETO_KMZ_1_8.json')) == ref.PROFILE18_SHA
        review_raw = (ROOT / 'resultado_perfil_incluido.json').read_bytes()
        review = json.loads(review_raw)
        assert review['origen_evidencia'] == 'PERFIL_INCLUIDO_VERIFICADO'
        assert review['perfil_incluido_sha256'] == ref.PROFILE18_SHA
        assert review['destino']['verificado'] and review['destino']['campos_verificados'] == 3340
        assert not review['destino']['incidencias'] and review['campos_tipo_pendiente'] == 730
        target = ref.target_model(base)
        target_raw = encode(target)
        fields = ref.definitions(target)
        pending = [row for row in review['campos'] if row['tipo_pendiente_modelo']]
        assert len(pending) == 730
        decisions = []
        for row in sorted(pending, key=lambda r:(r['clase'], r['campo'])):
            key = row['clase'], row['campo']
            typ = ref.NUMERIC.get(key, 'TEXT')
            assert row['tipo_destino_recomendado'] == typ
            decisions.append(dict(clase=key[0], campo=key[1], tipo_anterior='TEXT', longitud_anterior=4000,
                tipo_objetivo=typ, longitud_objetivo=4000 if typ == 'TEXT' else None,
                aprobado=True, cambio_fisico=key in ref.NUMERIC,
                naturaleza='DECLARACION_KML_COMPLETA' if key in ref.NUMERIC else 'CONSERVACION_DOCUMENTADA',
                propuesta_revisada=row['propuesta'], tipo_original_observado=row['tipo_origen'],
                fundamento=row['fundamento'], bloqueos_mapeo=row['bloqueos_mapeo']))
        blocks = [
            dict(codigo='NULOS_LITERAL', resuelto=False, campos=[
                'lineas_transmision_existentes_osinergmin_recorte.longitud_subterranea',
                'lineas_transmision_existentes_osinergmin_recorte.maxima_tension_operativa',
                'subestacion_poligono.src_area_ha'],
                detalle='Definir y verificar la conversion de <Null> a nulo durante la preparacion de carga.'),
            dict(codigo='OFICINA_REGISTRAL', resuelto=False,
                campo='predios_inscritos_sunarp_recorte.oficina_registral', entidades_con_conflicto=253,
                detalle='El almacenamiento TEXT se confirma; la correspondencia de valores sigue abierta.'),
            dict(codigo='RUTAS_SIN_DESTINO', resuelto=False, rutas=2601, elementos=140319,
                detalle='Lectura realizada; falta asignar destino o documentar exclusion conforme al EFT.'),
            dict(codigo='G1_SIN_COMPROBAR_EN_CT6788', resuelto=False, archivos=4,
                detalle='El perfil incluido tiene los13 originales; la lectura en CT6788 solo incorporo9.'),
            dict(codigo='DATASETS_RESTANTES', resuelto=False, datasets=['Datos_Externos', 'Datos_Internos'])]
        config = dict(version_paquete='1.9', version_modelo=12, version_modelo_origen=11,
            aprobado=True, autorizacion='Usuario: procede, tras propuesta de cerrar722TEXT y8numericos.',
            fecha_aprobacion='2026-11-09', modelo_origen_sha256=ref.MODEL11_SHA,
            modelo_objetivo_sha256=ref.sha(target_raw), perfil_origen_sha256=ref.PROFILE18_SHA,
            informe_sde_previo_sha256=ref.sha(review_raw), campos_confirmados=730,
            textos_confirmados=722, campos_pendientes_antes=730, campos_pendientes_despues=0,
            cambios_fisicos=ref.changes(), campos=decisions,
            bloqueos_ingesta=blocks, ingesta_autorizada=False)
        for name, raw in ((ref.BASE_NAME, baseline_raw), ('esquema.json', target_raw),
                          (ref.CONFIG_NAME, encode(config))):
            write(name, raw)
        for name in ('campos_aprobados_1_5.json', 'nombres_clases_1_6.json'):
            prior = json.loads(archive.read(name))
            prior['version_modelo'] = 12
            if name == 'nombres_clases_1_6.json':
                prior['modelo_objetivo_sha256'] = ref.sha(target_raw)
            write(name, prior)
        decision_keys = {(r['clase'], r['campo']) for r in decisions}
        def update_matrix(row):
            key = row['clase_destino'], row['campo_destino']
            if key in decision_keys:
                spec = fields[key]
                row.update(tipo=spec['tipo'], longitud=spec['longitud'] or '',
                    estado='MAPEADO_TIPO_CONFIRMADO_1_9')
                if key[1] == 'oficina_registral':
                    row['estado'] = 'TIPO_CONFIRMADO_MAPEO_POR_RESOLVER'
        def update_review(row):
            key = row['clase'], row['campo']
            if key in decision_keys:
                spec = fields[key]
                row.update(tipo_actual=spec['tipo'], longitud_actual=spec['longitud'] or '',
                    tipo_confirmado=spec['tipo'], longitud_confirmada=spec['longitud'] or '',
                    estado='TIPO_CONFIRMADO_1_9',
                    observacion='Decision de almacenamiento aprobada en cierre1.9; no acredita ingesta ni mapeo.')
        write('campos_matriz_a_esquema.csv', csv_update(archive.read('campos_matriz_a_esquema.csv'), update_matrix))
        write('revision_tipos.csv', csv_update(archive.read('revision_tipos.csv'), update_review))
        # El mapa de rutas/atributos no cambia: tipo confirmado no resuelve mapeos.
        assert (OUT / 'campos_por_ruta.csv').read_bytes() == archive.read('campos_por_ruta.csv')
        for name in ('esquema.sql',):
            if name in manifest['archivos']:
                raise ValueError('Revisar DDL derivado antes de publicar el modelo nuevo.')
    ref.read_reference(OUT)
    report = dict(version_paquete='1.9', estado='MODELO_CIERRE_PREPARADO',
        modelo_origen_sha256=ref.MODEL11_SHA, modelo_objetivo_sha256=ref.sha(target_raw),
        campos_confirmados=730, textos_sin_cambio_fisico=722, cambios_fisicos=ref.changes(),
        campos_provisionales_objetivo=0, cambios_en_sde=False, ingesta_autorizada=False,
        archivos_sha256={name:ref.sha((OUT/name).read_bytes()) for name in [
            'esquema.json',ref.BASE_NAME,ref.CONFIG_NAME,'campos_aprobados_1_5.json',
            'nombres_clases_1_6.json','campos_matriz_a_esquema.csv','revision_tipos.csv']})
    write('VALIDACION_MODELO_CIERRE_1_9.json', report)
    print('Modelo12 preparado:730 decisiones,722TEXT sin cambio fisico y8 cambios numericos; SDE sin tocar.')


if __name__ == '__main__':
    main()
