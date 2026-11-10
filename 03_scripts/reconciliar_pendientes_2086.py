"""Cruza la revision de tipos con el modelo vigente, sin modificarlo ni abrir SDE."""
import collections
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / '02_entregas/Esquema_KMZ_EFT_Corregido'
PROFILE = ROOT / '02_entregas/Revision_Tipos_Datos_Proyecto/revision_2185_campos.csv'
OUT = ROOT / '02_entregas/Revision_Pendientes_2086'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    paths = [PROFILE] + [MODEL_DIR/name for name in (
        'esquema.json', 'nombres_clases_1_6.json', 'campos_aprobados_1_5.json', 'PERFIL_GENERAL_ORIGEN.json')]
    original_hashes = {str(path): sha(path) for path in paths}
    model = read(paths[1])
    mapping = read(paths[2])
    approvals = read(paths[3])
    profile_meta = read(paths[4])
    translations = {row['nombre_anterior']: row['nombre_nuevo'] for row in mapping['clases']}
    definitions = {(cls['nombre'], field['nombre']): field for cls in model['clases']
                   for field in cls['campos'] if 'pendiente' in field.get('origen', '').lower()}
    with PROFILE.open(encoding='utf-8-sig', newline='') as stream:
        source_rows = list(csv.DictReader(stream, delimiter=';'))
    rows = {}
    for row in source_rows:
        key = (translations[row['clase']], row['campo'])
        assert key not in rows, key
        rows[key] = row
    approved = {(change['clase'], change['campo']) for change in approvals['cambios']}
    assert len(definitions) == 2086 and len(rows) == 2185 and len(approved) == 99
    assert set(definitions) <= set(rows) and set(rows) - set(definitions) == approved
    assert not set(definitions) & approved
    source_verification = []
    for source in profile_meta['fuentes']:
        path = Path(source['ruta_lectura'])
        digest = sha(path)
        assert digest == source['sha256'], source['archivo']
        source_verification.append(dict(archivo=source['archivo'], sha256=digest))
    details = []
    for (cls, field), spec in sorted(definitions.items()):
        row = rows[(cls, field)]
        useful = int(row['numericos']) + int(row['otros_textos'])
        proposal = row['propuesta']
        assert spec['tipo'] == 'TEXT' and spec['longitud'] == 4000
        assert row['cobertura'] == 'COMPLETA_RUTAS_DEL_CAMPO' and not row['fuentes_ausentes']
        assert int(row['longitud_maxima_utf16']) <= spec['longitud']
        if row['bloqueos']:
            group = 'CONFLICTO_DE_MAPEO'
        elif useful == 0:
            group = 'SIN_VALORES_UTILES'
        elif proposal in ('MANTENER_TEXT_CONTENIDO', 'MANTENER_TEXT_IDENTIFICADOR_O_ETIQUETA'):
            group = 'CANDIDATO_A_CONFIRMAR_TEXT'
        elif proposal == 'REVISAR_NUMERICO_SIN_SEMANTICA':
            group = 'REVISAR_SIGNIFICADO_NUMERICO'
        elif proposal == 'REVISAR_FECHA':
            group = 'REVISAR_FECHA_CON_VALORES'
        elif proposal == 'REVISAR_CEROS_INICIALES':
            group = 'PRESERVAR_CEROS_Y_REVISAR_CODIGO'
        else:
            raise AssertionError((cls, field, proposal))
        details.append(dict(clase=cls, campo=field, clase_en_perfil=row['clase'],
            tipo_actual='TEXT', longitud_actual=4000, grupo_revision=group,
            propuesta_historica=proposal, aprobado=False, cambio_fisico_propuesto=False,
            valores_utiles=useful, registros_con_campo=int(row['registros_con_campo']),
            vacios=int(row['vacios']), marcadores_literales=int(row['marcadores_literales']),
            longitud_maxima_utf16=int(row['longitud_maxima_utf16']),
            ceros_iniciales=int(row['ceros_iniciales']),
            digitos_significativos_max=int(row['digitos_significativos_max']),
            cobertura=row['cobertura'], bloqueos=row['bloqueos'], fundamento=row['fundamento']))
    groups = dict(collections.Counter(item['grupo_revision'] for item in details))
    expected = dict(CANDIDATO_A_CONFIRMAR_TEXT=1356, CONFLICTO_DE_MAPEO=1,
        SIN_VALORES_UTILES=187, REVISAR_SIGNIFICADO_NUMERICO=474,
        REVISAR_FECHA_CON_VALORES=47, PRESERVAR_CEROS_Y_REVISAR_CODIGO=21)
    assert groups == expected and sum(groups.values()) == 2086
    report = dict(estado='BORRADOR_DE_REVISION_SIN_APROBACIONES', version_modelo=model['version'],
        campos_pendientes=len(details), clases_con_pendientes=len({item['clase'] for item in details}),
        grupos=groups, cambios_aprobados_ya_excluidos=99, cambios_en_modelo=False, cambios_en_sde=False,
        fuentes_sha256=original_hashes, kmz_verificados=source_verification,
        alcance=dict(rutas_del_perfil=profile_meta['rutas_inventariadas'],
            asignaciones_del_perfil=profile_meta['asignaciones_observadas'],
            cobertura='Rutas asignadas del perfil historico, no todas las rutas KMZ pendientes de destino.'),
        limitaciones=[
            'No aprueba tipos ni actualiza el contador de campos provisionales.',
            'La propuesta textual no resuelve por si sola la equivalencia de atributos o el mapeo de carga.',
            'Las fechas requieren revisar formatos y literales; los valores numericos requieren significado y precision.',
            'OFICINA REGISTRAL duplicada requiere un mapeo explicito que preserve ambas ocurrencias.',
            'Los valores vacios o marcadores no prueban un tipo definitivo.',
            'No se ha abierto la conexion SDE; la validacion en destino fue comunicada por el usuario.'],
        campos=details)
    assert all(sha(Path(path)) == digest for path, digest in original_hashes.items())
    OUT.mkdir(exist_ok=True)
    destination = OUT / 'revision_pendientes_2086.json'
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(archivo=str(destination), campos=len(details), grupos=groups,
                         kmz_sha_verificados=len(source_verification), fuentes_sin_cambios=True)))


if __name__ == '__main__':
    main()
