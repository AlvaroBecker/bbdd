"""Validacion completa de tipos KMZ; consultas y archivos nuevos, sin DDL.

Las propuestas no cambian el modelo ni aprueban la ingesta. La comprobacion
del perfil incluido verifica su evidencia archivada, no los KMZ de otro equipo.
"""
from __future__ import annotations

from collections import Counter
import csv
import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
from types import SimpleNamespace
import uuid

import datos_proyecto as runner

HERE = Path(__file__).resolve().parent
SNAPSHOT = 'PERFIL_COMPLETO_KMZ_1_8.json'
SNAPSHOT_SHA = 'PERFIL_COMPLETO_KMZ_1_8.sha256'
SNAPSHOT_1_9 = 'PERFIL_COMPLETO_KMZ_1_9.json'
SNAPSHOT_SHA_1_9 = 'PERFIL_COMPLETO_KMZ_1_9.sha256'
REFERENCES = ('esquema.json', 'mapeo_capas_revision.csv', 'campos_por_ruta.csv',
              'inspeccion_kmz.py', 'validar_tipos_kmz.py')
CLOSURE_REFERENCES = ('referencia_cierre_tipos.py', 'cierre_tipos_1_9.json',
                      'esquema_anterior_1_8.json')
MARKERS = {'<null>', 'null', '<nulo>', 'nulo', 'none', 'nan', 'n/a'}
NUMBER = re.compile(r'^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$')
ISO_DATE = re.compile(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[T ][0-9]{2}:[0-9]{2}(?::[0-9]{2}(?:\.[0-9]+)?)?(?:Z|[+-][0-9]{2}:[0-9]{2})?)?$')
AMBIGUOUS_DATE = re.compile(r'^([0-9]{1,2})[/-]([0-9]{1,2})[/-]([0-9]{2}|[0-9]{4})(?:\s.*)?$')
KML_TYPES = {'string', 'int', 'uint', 'short', 'ushort', 'float', 'double', 'bool'}
FLOAT32_MAX = Decimal('340282346638528859811704183484516925440')
FLOAT32_MIN_SUBNORMAL = Decimal('1.40129846432481707092372958328991613128026194187651577175706828388979108268586060148663818836212158203125e-45')
require = runner.engine.require


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def value_flags(value):
    """Clasifica una representacion completa sin transformarla ni truncarla."""
    flags = []
    def add(name):
        flags.append(name)
    text = str(value).strip()
    if not text:
        add('vacios')
        return flags
    if text.casefold() in MARKERS:
        add('marcadores')
        return flags
    add('utiles')
    if re.fullmatch(r'[+-]?[0-9]+', text):
        add('enteros_lexicos')
    if text in {'true', 'false', '0', '1'}:
        add('booleanos_kml')
    number = None
    if NUMBER.fullmatch(text):
        try:
            number = Decimal(text)
        except InvalidOperation:
            pass
    if number is not None and number.is_finite():
        add('numericos')
        if number != number.to_integral_value():
            add('fraccionarios')
        if not Decimal(-32768) <= number <= Decimal(32767):
            add('fuera_short')
        if not Decimal(-2147483648) <= number <= Decimal(2147483647):
            add('fuera_long')
        if not Decimal(0) <= number <= Decimal(65535):
            add('fuera_ushort')
        if not Decimal(0) <= number <= Decimal(4294967295):
            add('fuera_uint')
        magnitude = number.copy_abs()
        if magnitude > FLOAT32_MAX:
            add('float32_fuera_rango')
        if 0 < magnitude < FLOAT32_MIN_SUBNORMAL:
            add('float32_menor_subnormal')
        if len(number.as_tuple().digits) > 15:
            add('precision_mayor_15')
        if re.fullmatch(r'[+-]?0[0-9]+(?:\.[0-9]*)?', text):
            add('ceros_iniciales')
        if number < 0:
            add('negativos')
        if number in {Decimal(-1), Decimal(-99), Decimal(-999)}:
            add('negativos_convencion_posible')
        try:
            converted = float(number)
            if not math.isfinite(converted):
                add('double_no_finito')
            elif Decimal(str(converted)) != number:
                add('double_roundtrip_diferente')
        except (ValueError, OverflowError):
            add('double_no_finito')
    else:
        add('no_numericos')
        if text.casefold() in {'inf', '+inf', '-inf', 'infinity', '+infinity', '-infinity'}:
            add('no_finitos')
    parsed = None
    if ISO_DATE.fullmatch(text):
        try:
            parsed = dt.datetime.fromisoformat(text.replace('Z', '+00:00'))
        except ValueError:
            pass
    if parsed is not None:
        add('fechas_iso')
        if parsed.tzinfo is not None:
            add('fechas_zona_horaria')
        fraction = re.search(r':[0-9]{2}\.([0-9]+)', text)
        if parsed.microsecond or (fraction and any(char != '0' for char in fraction[1])):
            add('fechas_subsegundos')
        if fraction and len(fraction[1]) > 6:
            add('fechas_precision_mayor_microsegundo')
        if not 100 <= parsed.year <= 9999:
            add('fechas_fuera_rango')
    else:
        add('fechas_no_iso')
        match = AMBIGUOUS_DATE.fullmatch(text)
        if match and 1 <= int(match[1]) <= 12 and 1 <= int(match[2]) <= 12:
            add('fechas_ambiguas')
    return flags


def observe_validation(stats, value, declared=None):
    """Acumula todos los valores y el subconjunto exacto de cada tipo declarado."""
    flags = value_flags(value)
    counter = stats.setdefault('validacion_valores', {})
    for name in flags:
        counter[name] = counter.get(name, 0) + 1
    if declared is not None:
        declared_counter = stats.setdefault('validacion_valores_por_tipo', {}).setdefault(str(declared), {})
        for name in flags:
            declared_counter[name] = declared_counter.get(name, 0) + 1


def evaluate_source_declaration(stats):
    """Valida tipos KML de cada fuente, incluso atributos sin clase de destino."""
    declared = {str(key): int(value) for key, value in stats.get('tipos_declarados', {}).items() if value}
    typed = stats.get('validacion_valores_por_tipo', {})
    issues, checks = [], []
    if not declared:
        return dict(validacion_tipo_origen='SIN_TIPO_DECLARADO', incidencias_tipo_origen=[],
            detalle_tipos_origen=[], valores_sin_tipo=stats.get('valores_sin_tipo',0),
            fundamento_tipo_origen='Se perfilaron los valores. La fuente no declara un tipo; no se inventa uno.')
    for name, count in sorted(declared.items()):
        require(name in typed, 'Falta evidencia exhaustiva por tipo declarado; regenere el perfil 1.8.')
        counters = typed[name]
        total = sum(counters.get(key,0) for key in ('utiles','vacios','marcadores'))
        require(total == count, 'No coincide el numero de valores con su tipo declarado: ' + name)
        kind = name.casefold()
        errors = []
        useful = counters.get('utiles',0)
        if kind not in KML_TYPES:
            errors.append('DECLARACION_KML_NO_ESTANDAR')
        elif kind in {'int','uint','short','ushort'}:
            if counters.get('enteros_lexicos',0) != useful:
                errors.append('DECLARACION_ENTERA_LEXEMA_INVALIDO')
            limit = {'int':'long','uint':'uint','short':'short','ushort':'ushort'}[kind]
            if counters.get('fuera_' + limit,0):
                errors.append('DECLARACION_ENTERA_FUERA_RANGO')
        elif kind == 'bool':
            if counters.get('booleanos_kml',0) != useful:
                errors.append('DECLARACION_BOOL_LEXEMA_INVALIDO')
        elif kind in {'float','double'}:
            if counters.get('no_numericos',0):
                errors.append('DECLARACION_FLOTANTE_VALOR_NO_NUMERICO')
            if counters.get('double_no_finito',0) or counters.get('no_finitos',0):
                errors.append('DECLARACION_FLOTANTE_NO_FINITA_PARA_DESTINO')
            if counters.get('double_roundtrip_diferente',0):
                errors.append('DECLARACION_FLOTANTE_REQUIERE_PRECISION')
            if kind == 'float' and counters.get('float32_fuera_rango',0):
                errors.append('DECLARACION_FLOAT_FUERA_RANGO_32_BITS')
            if kind == 'float' and counters.get('float32_menor_subnormal',0):
                errors.append('DECLARACION_FLOAT_REQUIERE_REGLA_SUBDESBORDAMIENTO')
        if kind != 'string' and (counters.get('vacios',0) or counters.get('marcadores',0)):
            errors.append('DECLARACION_NO_TEXTUAL_REQUIERE_REGLA_NULL')
        checks.append(dict(tipo_declarado=name,valores=count,estadisticas=counters,incidencias=errors))
        issues.extend(errors)
    if len(declared) > 1:
        issues.append('DECLARACIONES_MULTIPLES_EN_EL_CAMPO')
    status = ('DECLARACION_CON_INCIDENCIAS' if issues else 'DECLARACION_PARCIAL'
              if stats.get('valores_sin_tipo',0) else 'DECLARACION_VERIFICADA')
    return dict(validacion_tipo_origen=status, incidencias_tipo_origen=sorted(set(issues)),
        detalle_tipos_origen=checks, valores_sin_tipo=stats.get('valores_sin_tipo',0),
        fundamento_tipo_origen='Cada tipo se contrasta solo con los valores que lo declaran. Los valores sin tipo no heredan esa declaracion.')


def package_version(version):
    require(version in (11, 12), 'Se requiere el modelo 11 o el modelo 12 con cierre verificado.')
    return '1.8' if version == 11 else '1.9'


def model_version(model_dir):
    version = json.loads((Path(model_dir) / 'esquema.json').read_text(encoding='utf-8-sig')).get('version')
    package_version(version)
    return version


def snapshot_names(model_dir=None, version=None):
    version = model_version(model_dir or HERE) if version is None else version
    package_version(version)
    return (SNAPSHOT, SNAPSHOT_SHA) if version == 11 else (SNAPSHOT_1_9, SNAPSHOT_SHA_1_9)


def validated_model(model_dir, model):
    """El modelo 12 exige la referencia de cierre; la rama 11 sigue siendo independiente."""
    package_version(model.get('version'))
    if model['version'] == 12:
        from referencia_cierre_tipos import read_reference
        _, target, _ = read_reference(Path(model_dir))
        require(target == model, 'El modelo no coincide con el objetivo del cierre 1.9.')
        require(not any(runner.provisional(field) for cls in model['clases'] for field in cls['campos']),
                'El cierre del modelo 12 debe conservar cero tipos provisionales.')
    return runner.scoped_model(model)


def input_hashes(model_dir):
    version = model_version(model_dir)
    names = REFERENCES + (CLOSURE_REFERENCES if version == 12 else ())
    return {name: digest(Path(model_dir) / name) for name in names}


def build_profile(kmz_dir, model_dir=None, emit=print):
    """Construye evidencia en memoria; el caller decide donde archivarla."""
    from inspeccion_kmz import collect
    model_dir = Path(model_dir or HERE).resolve()
    before = input_hashes(model_dir)
    model = validated_model(model_dir, json.loads((model_dir / 'esquema.json').read_text(encoding='utf-8-sig')))
    require(len(model['clases']) == 76, 'La validacion requiere las 76 clases del modelo.')
    profile = collect(kmz_dir, model_dir, emit=emit, value_observer=observe_validation)
    require(input_hashes(model_dir) == before, 'Las referencias cambiaron durante el perfilado.')
    return dict(version_paquete=package_version(model['version']), version_modelo=model['version'],
        generado_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        referencias_sha256=before, perfil=profile, cambios_en_modelo=False, cambios_en_sde=False)


def write_profile_snapshot(envelope, model_dir=None):
    """Escritura explicita para preparar el paquete; nunca se llama desde run."""
    model_dir = Path(model_dir or HERE).resolve()
    version = model_version(model_dir)
    require(envelope.get('version_modelo') == version
            and envelope.get('version_paquete') == package_version(version),
            'El perfil a archivar no corresponde a la version del modelo.')
    raw = (json.dumps(envelope, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    snapshot, snapshot_sha = snapshot_names(version=version)
    target = model_dir / snapshot
    sidecar = model_dir / snapshot_sha
    require(not target.exists() and not sidecar.exists(), 'El perfil archivado ya existe; no se sobrescribe.')
    with target.open('xb') as stream:
        stream.write(raw)
    with sidecar.open('x', encoding='ascii') as stream:
        stream.write(hashlib.sha256(raw).hexdigest() + '\n')
    return target


def read_profile_snapshot(model_dir):
    model_dir = Path(model_dir)
    model = json.loads((model_dir / 'esquema.json').read_text(encoding='utf-8-sig'))
    validated_model(model_dir, model)
    snapshot, snapshot_sha = snapshot_names(version=model['version'])
    target, sidecar = model_dir / snapshot, model_dir / snapshot_sha
    expected = sidecar.read_text(encoding='ascii').strip()
    require(re.fullmatch(r'[0-9a-f]{64}', expected), 'Huella del perfil incluido no valida.')
    raw = target.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == expected, 'El perfil incluido fue modificado o esta incompleto.')
    envelope = json.loads(raw)
    require(envelope.get('version_paquete') == package_version(model['version'])
            and envelope.get('version_modelo') == model['version'],
            'Version del perfil incluido incompatible.')
    require(envelope.get('referencias_sha256') == input_hashes(model_dir),
            'El perfil no corresponde al modelo, mapeos o codigo de esta carpeta.')
    require(isinstance(envelope.get('perfil'), dict), 'Falta el perfil completo incluido.')
    return envelope, expected


def evaluate_field(spec, stats):
    """Separar capacidad actual, evidencia de fuente y propuesta sin aprobacion."""
    pending = runner.provisional(spec)
    answer = dict(tipo_actual=spec['tipo'], longitud_actual=spec.get('longitud'),
        tipo_pendiente_modelo=pending, compatibilidad='SIN_VALORES_OBSERVADOS',
        propuesta='CONSERVAR_MODELO_CONFIRMADO' if not pending else 'CONSERVAR_TEXT_SIN_EVIDENCIA',
        tipo_propuesto=spec['tipo'], aprobado=False, requiere_decision=pending,
        motivos=[], incidencias=[], cobertura='SIN_PERFIL',
        tipo_declarado=None, declaracion_completa=False)
    def finish():
        answer['tipo_origen'] = answer['tipo_declarado'] or (
            'NO_APLICA_TIPO_ORIGEN' if answer['compatibilidad'] == 'NO_APLICA_TIPO_ORIGEN'
            else 'SIN_DECLARACION_UNICA_COMPLETA')
        if answer['tipo_declarado'] and not answer['declaracion_completa']:
            answer['tipo_origen'] += ' (declaracion parcial)'
        answer['tipo_destino_recomendado'] = answer['tipo_propuesto']
        answer['longitud_destino_recomendada'] = (max(spec.get('longitud') or 0,
            int((stats or {}).get('max_utf16', 0))) if answer['tipo_propuesto'] == 'TEXT' else None)
        answer['fundamento'] = ' '.join(answer['motivos']) or 'Se conserva la definicion confirmada del modelo; consultar compatibilidad y alcance.'
        answer['naturaleza_recomendacion'] = ('CANDIDATO_BASADO_EN_DECLARACION' if answer['propuesta'].startswith('CANDIDATO_')
            else 'CONSERVACION_DOCUMENTADA' if pending else 'MODELO_PREVIAMENTE_CONFIRMADO')
        answer['bloqueos_mapeo'] = [code for code in answer['incidencias']
            if code in {'CONFLICTO_MAPEO_VALORES','COBERTURA_INCOMPLETA'}]
        type_issues = [code for code in answer['incidencias'] if code not in answer['bloqueos_mapeo']]
        answer['compatibilidad_tipo'] = ('REQUIERE_REVISION' if type_issues else
            'COMPATIBLE_VALORES_OBSERVADOS' if stats and stats.get('registros') else answer['compatibilidad'])
        return answer
    if stats is None or not stats.get('registros'):
        if not spec.get('campo_fuente'):
            answer.update(compatibilidad='NO_APLICA_TIPO_ORIGEN', propuesta='CONSERVAR_DEFINICION_EFT_DDL',
                          cobertura='DERIVADO_O_ENTRADA_DE_CARGA')
            answer['motivos'].append('Campo comun, derivado, llave o DDL: validar su regla de generacion o entrada durante la preparacion de carga. La ausencia en KMZ no es una muestra vacia.')
        else:
            answer['motivos'].append('No hay valores fuente observados para evaluar conversiones; se propone conservar TEXT sin inventar un tipo original.')
        return finish()
    answer['cobertura'] = stats.get('cobertura', 'INCOMPLETA')
    values = stats.get('validacion_valores')
    require(isinstance(values, dict), 'El perfil carece de validacion exhaustiva de valores; regenere el perfil 1.8.')
    useful = int(stats.get('valores_utiles', 0))
    require(values.get('utiles', 0) == useful, 'Los contadores exhaustivos no coinciden con los valores utiles.')
    issues = answer['incidencias']
    maximum = int(stats.get('max_utf16', 0))
    if stats.get('conflictos', 0):
        issues.append('CONFLICTO_MAPEO_VALORES')
    if answer['cobertura'] != 'COMPLETA_RUTAS_DEL_CAMPO':
        issues.append('COBERTURA_INCOMPLETA')
    if spec['tipo'] == 'TEXT':
        if maximum > spec['longitud']:
            issues.append('LONGITUD_INSUFICIENTE')
            answer['motivos'].append('La longitud propuesta es la capacidad minima observada en unidades UTF-16. Su almacenamiento debe resolverse con un tipo admitido por la geodatabase y SQL Server; no se aplica un AlterField automatico.')
    elif useful:
        if spec['tipo'] in {'SHORT', 'LONG', 'DOUBLE'}:
            if values.get('no_numericos', 0):
                issues.append('VALORES_NO_NUMERICOS')
            if spec['tipo'] in {'SHORT', 'LONG'}:
                if values.get('fraccionarios', 0):
                    issues.append('FRACCIONES_EN_ENTERO')
                if values.get('fuera_' + spec['tipo'].lower(), 0):
                    issues.append('FUERA_RANGO_' + spec['tipo'])
            else:
                if values.get('double_no_finito', 0) or values.get('no_finitos', 0):
                    issues.append('DOUBLE_NO_FINITO')
                if values.get('double_roundtrip_diferente', 0):
                    issues.append('DOUBLE_CAMBIA_VALOR_DECIMAL')
                if stats.get('max_significant', 0) > 15:
                    issues.append('PRECISION_MAYOR_15_DIGITOS')
            if values.get('ceros_iniciales', 0):
                issues.append('CEROS_INICIALES_SE_PERDERIAN')
        elif spec['tipo'] == 'DATE':
            if values.get('fechas_no_iso', 0):
                issues.append('FECHA_FORMATO_NO_UNIVOCO_O_INVALIDO')
            if values.get('fechas_zona_horaria', 0):
                issues.append('FECHA_ZONA_HORARIA_REQUIERE_REGLA')
            if values.get('fechas_subsegundos', 0):
                issues.append('FECHA_SUBSEGUNDOS_REQUIERE_PRECISION')
            if values.get('fechas_fuera_rango', 0):
                issues.append('FECHA_FUERA_RANGO')
    if spec['tipo'] != 'TEXT' and values.get('marcadores', 0):
        issues.append('MARCADORES_REQUIEREN_REGLA_NULL')
    if not spec.get('nullable', True) and values.get('vacios', 0):
        issues.append('VACIOS_EN_CAMPO_OBLIGATORIO')
    answer['compatibilidad'] = 'COMPATIBLE_VALORES_OBSERVADOS' if not issues else 'REQUIERE_REVISION'
    declared = {str(k).lower(): int(v) for k, v in stats.get('tipos_declarados', {}).items() if v}
    fully_declared = bool(declared) and not stats.get('valores_sin_tipo', 0)
    answer['declaracion_completa'] = fully_declared
    source_check = evaluate_source_declaration(stats)
    answer['validacion_declaracion_origen'] = source_check['validacion_tipo_origen']
    answer['incidencias_declaracion_origen'] = source_check['incidencias_tipo_origen']
    if len(declared) == 1:
        answer['tipo_declarado'] = next(iter(declared))
    if not pending:
        if issues:
            answer['propuesta'] = 'REVISAR_COMPATIBILIDAD_MODELO_CONFIRMADO'
            answer['requiere_decision'] = True
        if source_check['incidencias_tipo_origen']:
            answer['requiere_decision'] = True
            if not issues:
                answer['propuesta'] = 'REVISAR_DECLARACION_ORIGEN_MODELO_CONFIRMADO'
            answer['motivos'].append('El destino conserva su definicion confirmada, pero la declaracion del origen tiene incidencias que requieren una decision separada de la capacidad fisica.')
        return finish()
    answer['tipo_propuesto'] = 'TEXT'
    if issues:
        answer['propuesta'] = 'RESOLVER_INCIDENCIAS_ANTES_DE_TIPIFICAR'
        answer['motivos'].append('La fuente o el mapeo tiene incidencias; no se propone una conversion automatica.')
    elif not useful:
        answer['propuesta'] = 'CONSERVAR_TEXT_SIN_VALORES_UTILES'
        answer['motivos'].append('Los vacios o marcadores no permiten justificar otro tipo.')
    elif len(declared) > 1:
        answer['propuesta'] = 'CONSERVAR_TEXT_DECLARACIONES_DISTINTAS'
        answer['motivos'].append('Las fuentes declaran tipos diferentes; requiere resolver la correspondencia.')
    elif not fully_declared:
        answer['propuesta'] = 'CONSERVAR_TEXT_TIPO_ORIGEN_INCOMPLETO'
        answer['motivos'].append('Una parte o todos los valores carecen de tipo declarado; el nombre y las cifras no aprueban una conversion.')
    else:
        original = answer['tipo_declarado']
        if original not in KML_TYPES:
            answer['propuesta'] = 'CONSERVAR_TEXT_TIPO_KML_NO_ESTANDAR'
            answer['motivos'].append('Declaracion KML no estandar: ' + original + '. No se equipara por nombre con un tipo ArcGIS.')
        elif source_check['incidencias_tipo_origen']:
            answer['propuesta'] = 'CONSERVAR_TEXT_DECLARACION_INCOMPATIBLE'
            answer['motivos'].append('Los valores declarados requieren revisar lexemas, rango o reglas NULL antes de proponer un tipo numerico.')
        elif original == 'string':
            answer['propuesta'] = 'CANDIDATO_CONFIRMAR_TEXT_DECLARADO'
            answer['motivos'].append('Todos los valores tienen declaracion string; se conserva su representacion.')
        elif original == 'bool':
            answer['propuesta'] = 'CONSERVAR_TEXT_BOOLEANO_REQUIERE_MAPEO'
            answer['motivos'].append('La representacion booleana requiere una regla explicita de dominio/conversion; no se crea una extension.')
        elif values.get('no_numericos', 0) or values.get('marcadores', 0) or values.get('ceros_iniciales', 0):
            answer['propuesta'] = 'CONSERVAR_TEXT_VALORES_REQUIEREN_REGLAS'
            answer['motivos'].append('Texto, marcadores o ceros iniciales requieren reglas antes de una conversion numerica.')
        elif original in {'short', 'ushort', 'int', 'uint'}:
            target = 'SHORT' if original == 'short' else 'LONG'
            if values.get('fraccionarios', 0) or values.get('fuera_' + target.lower(), 0):
                answer['propuesta'] = 'CONSERVAR_TEXT_DECLARACION_INCOMPATIBLE'
                answer['motivos'].append('Los valores no caben en el entero de destino o incluyen fracciones.')
            else:
                answer.update(propuesta='CANDIDATO_' + target + '_DECLARADO', tipo_propuesto=target)
                answer['motivos'].append('Declaracion entera completa y valores en rango; requiere aprobar la decision y su migracion.')
        elif original in {'float', 'double'}:
            if (values.get('double_no_finito', 0) or values.get('double_roundtrip_diferente', 0)
                    or stats.get('max_significant', 0) > 15):
                answer['propuesta'] = 'CONSERVAR_TEXT_PRECISION_NUMERICA'
                answer['motivos'].append('La precision o representacion necesita una decision; no se redondea.')
            else:
                answer.update(propuesta='CANDIDATO_DOUBLE_DECLARADO', tipo_propuesto='DOUBLE')
                answer['motivos'].append('Declaracion flotante completa y valores compatibles; requiere aprobar la decision y su migracion.')
    return finish()


class ReadOnlyArcPy:
    _allowed = frozenset(('GetInstallInfo', 'Exists', 'Describe', 'EnvManager',
        'ValidateTableName', 'ValidateFieldName', 'ListDatasets', 'ListFeatureClasses',
        'ListTables', 'ListFields'))

    def __init__(self, wrapped):
        self._wrapped = wrapped
        self.da = SimpleNamespace(ListDomains=wrapped.da.ListDomains)

    def __getattr__(self, name):
        if name not in self._allowed:
            raise AttributeError('API no admitida en validacion de lectura: ' + name)
        return getattr(self._wrapped, name)


def inspect_destination(arcpy_module, workspace, database, owner, model):
    a = ReadOnlyArcPy(arcpy_module)
    args = SimpleNamespace(workspace=os.path.abspath(workspace), database=database, owner=owner, aplicar=False)
    require(a.Exists(args.workspace), 'La conexion/geodatabase existente no se encuentra.')
    rows, issues = [], []
    with a.EnvManager(overwriteOutput=False, extent=None):
        inventory, domains = runner.engine.inspect(a, args, model, [])
        ds = inventory.get(runner.DATASET.casefold())
        require(ds and a.Describe(ds).dataType == 'FeatureDataset', 'Falta el feature dataset Datos_Proyecto.')
        for cls in model['clases']:
            path = inventory.get(cls['nombre'].casefold())
            actual, class_error = {}, None
            try:
                require(path is not None, 'Clase inexistente.')
                desc = a.Describe(path)
                require(desc.dataType == 'FeatureClass', 'El objeto no es una feature class.')
                require(runner.engine.simple(os.path.basename(desc.path)).casefold() == runner.DATASET.casefold(),
                        'Clase fuera de Datos_Proyecto.')
                require(desc.shapeType.casefold() == cls['geometria'].casefold()
                        and desc.spatialReference.factoryCode == 4326 and desc.hasZ and not desc.hasM,
                        'Geometria, SR, Z o M incompatibles.')
                require(desc.hasGlobalID and desc.editorTrackingEnabled and getattr(desc, 'isTimeInUTC', False),
                        'Falta GlobalID o auditoria UTC.')
                actual = runner.engine.field_index(a.ListFields(path))
            except Exception as exc:
                class_error = str(exc)
                issues.append(dict(clase=cls['nombre'], campo='*', propiedad='clase', detalle=class_error))
            for field in cls['campos']:
                found = actual.get(field['nombre'].casefold())
                row = dict(clase=cls['nombre'], campo=field['nombre'], ruta=path,
                    estado='NO_VERIFICADO', tipo_esperado=runner.engine.TYPE[field['tipo']],
                    longitud_esperada=field.get('longitud'), tipo_actual=None, longitud_actual=None)
                rows.append(row)
                if class_error:
                    continue
                checks = []
                if found is None:
                    checks.append(('campo', 'Falta el campo del modelo.'))
                else:
                    row.update(nombre_actual=runner.engine.field_base_name(found), tipo_actual=found.type,
                        longitud_actual=found.length, nullable_actual=found.isNullable, dominio_actual=found.domain or '')
                    if row['nombre_actual'] != field['nombre']:
                        checks.append(('nombre', 'Nombre no normalizado o distinto del modelo.'))
                    if found.type != row['tipo_esperado']:
                        checks.append(('tipo', f"{found.type}; esperado {row['tipo_esperado']}."))
                    if field['tipo'] == 'TEXT' and found.length < field['longitud']:
                        checks.append(('longitud', f"{found.length}; minimo {field['longitud']}."))
                    if found.isNullable != field['nullable']:
                        checks.append(('nullable', 'Nulabilidad distinta del modelo.'))
                    if (found.domain or '') != (field.get('dominio') or ''):
                        checks.append(('dominio', 'Dominio distinto del modelo.'))
                    if field.get('dominio') and field['dominio'] not in domains:
                        checks.append(('dominio', 'El dominio esperado no existe.'))
                if not checks:
                    row['estado'] = 'VERIFICADO'
                issues.extend(dict(clase=cls['nombre'], campo=field['nombre'], propiedad=prop, detalle=message)
                              for prop, message in checks)
    return dict(arcgis=a.GetInstallInfo().get('Version'), campos=rows, incidencias=issues,
                campos_verificados=sum(row['estado'] == 'VERIFICADO' for row in rows),
                clases_esperadas=len(model['clases']), verificado=not issues)


def csv_rows(path, rows, columns=None):
    rows = list(rows)
    columns = columns or list(dict.fromkeys(key for row in rows for key in row)) or ['estado']
    with Path(path).open('x', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, columns, delimiter=';', extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False, sort_keys=True)
                if isinstance(value, (dict, list, tuple)) else value for key, value in row.items()})


def write_reports(folder, report, profile):
    folder.mkdir(parents=True, exist_ok=False)
    report.update(archivo_resultado=str(folder / 'resultado.json'), archivo_campos=str(folder / 'campos.csv'),
        archivo_fuentes=str(folder / 'campos_fuente.csv'), archivo_cobertura=str(folder / 'cobertura_rutas.csv'),
        archivo_incidencias=str(folder / 'incidencias.csv'), archivo_informe=str(folder / 'informe.md'))
    csv_rows(folder / 'campos.csv', report.get('campos', []))
    csv_rows(folder / 'campos_fuente.csv', profile.get('campos_fuente', []))
    csv_rows(folder / 'cobertura_rutas.csv', profile.get('rutas', []))
    csv_rows(folder / 'incidencias.csv', report.get('incidencias', []))
    if report.get('destino'):
        csv_rows(folder / 'campos_destino.csv', report['destino'].get('campos', []))
        report['archivo_destino'] = str(folder / 'campos_destino.csv')
    lines = [f"# Validacion conjunta de tipos KMZ {report['version_paquete']}", '', f"Estado: **{report['estado']}**", '',
        f"Origen de evidencia: {report.get('origen_evidencia', 'NO_LEIDA')}.",
        f"Campos del modelo revisados: {report.get('campos_revisados', 0)}.",
        f"Tipos pendientes en el modelo: {report.get('campos_tipo_pendiente', 'No evaluados')}.",
        f"Campos con incidencias de valores: {report.get('campos_con_incidencias', 0)}.", '',
        'El modelo y la geodatabase permanecen sin cambios. Las propuestas no son aprobaciones. '
        'Este resultado no autoriza ingesta: conserva por separado las discrepancias, el mapeo '
        'pendiente y los tipos que necesitan decision. Datos_Externos y Datos_Internos no se crean ni se certifican.', '']
    if report.get('origen_evidencia') == 'PERFIL_INCLUIDO_VERIFICADO':
        lines += ['Se verificaron los hashes del perfil archivado y sus referencias. Los KMZ originales '
                  'no se releyeron en esta ejecucion. Para validar archivos actuales, indique su carpeta.', '']
    if report.get('error'):
        lines += ['## Detencion', '', report['error'], '']
    lines += ['## Propuestas por campo', ''] + [f'- {key}: {value}.' for key, value in sorted(report.get('propuestas', {}).items())]
    with (folder / 'informe.md').open('x', encoding='utf-8') as stream:
        stream.write('\n'.join(lines) + '\n')
    with (folder / 'resultado.json').open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def run(workspace, kmz_dir=None, database='ArcGisAWS', owner='gis', reports=None,
        arcpy_module=None, emit=print, model_dir=None):
    model_dir = Path(model_dir or HERE).resolve()
    parent = Path(reports or model_dir).resolve()
    require(parent.is_dir(), 'La carpeta de informes debe existir.')
    folder = parent / ('Tipos_KMZ_' + dt.datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:12])
    report = dict(version_paquete='1.9', version_modelo=None, estado='ERROR_DETENIDO',
        modo='SOLO_LECTURA', inicio_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
        workspace=str(workspace) if workspace else None, database=database, owner=owner,
        campos=[], incidencias=[], cambios_en_modelo=False, cambios_en_sde=False,
        tipos_aprobados_en_esta_ejecucion=0, ingesta_autorizada=False, destino=None)
    profile, failure = {}, None
    try:
        source_model = json.loads((model_dir / 'esquema.json').read_text(encoding='utf-8-sig'))
        report.update(version_modelo=source_model.get('version'))
        report['version_paquete'] = package_version(source_model.get('version'))
        before = input_hashes(model_dir)
        model = validated_model(model_dir, source_model)
        fields = {(cls['nombre'], field['nombre']):field for cls in model['clases'] for field in cls['campos']}
        require(len(model['clases']) == 76 and len(fields) == 3340,
                'Se requiere el modelo completo: 76 clases y 3340 definiciones.')
        report.update(referencias_sha256=before, clases_modelo=76, campos_modelo=3340,
            campos_tipo_pendiente=sum(runner.provisional(field) for field in fields.values()))
        if kmz_dir:
            envelope = build_profile(kmz_dir, model_dir, emit=emit)
            report['origen_evidencia'] = 'LECTURA_KMZ_ACTUALES'
        else:
            envelope, fingerprint = read_profile_snapshot(model_dir)
            report.update(origen_evidencia='PERFIL_INCLUIDO_VERIFICADO', perfil_incluido_sha256=fingerprint)
        profile = envelope['perfil']
        report['fuentes'] = profile.get('fuentes', [])
        report['perfil_generado_utc'] = envelope.get('generado_utc')
        if envelope.get('perfil_original_sha256'):
            report['perfil_original_sha256'] = envelope['perfil_original_sha256']
        if envelope.get('reevaluado_utc'):
            report['perfil_reevaluado_utc'] = envelope['reevaluado_utc']
        report['resumen_perfil'] = {key:value for key,value in profile.items()
            if key not in {'campos_destino','campos_fuente','rutas','incidencias','fuentes'}}
        checked_sources = []
        for raw_field in profile.get('campos_fuente', []):
            checked = dict(raw_field, **evaluate_source_declaration(raw_field))
            checked_sources.append(checked)
            report['incidencias'].extend(dict(archivo=raw_field.get('archivo'),
                ruta=raw_field.get('ruta'), geometria=raw_field.get('geometria'),
                campo_original=raw_field.get('campo_original'), ocurrencia=raw_field.get('ocurrencia'),
                canal=raw_field.get('canal'), motivo=code,
                detalle='Contradiccion o regla pendiente en los valores del tipo declarado; ver campos_fuente.csv.')
                for code in checked['incidencias_tipo_origen'])
        profile['campos_fuente'] = checked_sources
        report['campos_fuente_revisados'] = len(checked_sources)
        report['validacion_tipos_fuente'] = dict(Counter(row['validacion_tipo_origen'] for row in checked_sources))
        report['campos_fuente_con_incidencias'] = sum(bool(row['incidencias_tipo_origen']) for row in checked_sources)
        source_fields = {(row['clase'], row['campo']):row for row in profile.get('campos_destino', [])}
        require(len(source_fields) == len(profile.get('campos_destino', [])), 'Campos destino duplicados en el perfil.')
        require(set(source_fields) <= set(fields), 'El perfil contiene destinos ajenos al modelo.')
        for key, field in sorted(fields.items()):
            stats = source_fields.get(key)
            row = dict(clase=key[0], campo=key[1], **evaluate_field(field, stats))
            if stats:
                row.update(estadisticas=stats)
                report['incidencias'].extend(dict(clase=key[0], campo=key[1], motivo=code,
                    detalle='Revisar evidencia completa en campos.csv.') for code in row['incidencias'])
            report['campos'].append(row)
        report['incidencias'].extend(profile.get('incidencias', []))
        report['campos_revisados'] = len(report['campos'])
        report['campos_con_incidencias'] = sum(bool(row['incidencias']) for row in report['campos'])
        report['propuestas'] = dict(Counter(row['propuesta'] for row in report['campos']))
        report['propuestas_pendientes'] = dict(Counter(row['propuesta'] for row in report['campos'] if row['tipo_pendiente_modelo']))
        report['tipos_recomendados_pendientes'] = dict(Counter(row['tipo_destino_recomendado'] for row in report['campos'] if row['tipo_pendiente_modelo']))
        report['campos_con_decision_pendiente'] = sum(row['requiere_decision'] for row in report['campos'])
        if workspace:
            if arcpy_module is None:
                import arcpy as arcpy_module
            report['destino'] = inspect_destination(arcpy_module, workspace, database, owner, model)
            report['incidencias'].extend(report['destino']['incidencias'])
        require(input_hashes(model_dir) == before, 'El modelo, mapeos o codigo cambiaron durante la validacion.')
        incomplete = (profile.get('estado') != 'LECTURA_COMPLETA' or
            any(row.get('estado') not in {'COINCIDE', 'SIN_DESTINO_COINCIDE'} for row in profile.get('rutas', [])))
        report['cobertura_completa'] = bool(profile.get('rutas')) and not incomplete
        if not report['cobertura_completa']:
            report['estado'] = 'VALIDACION_TIPOS_INCOMPLETA'
        elif (report['campos_tipo_pendiente'] or report['campos_con_decision_pendiente']
              or report['incidencias'] or any(not row.get('clase_destino', row.get('clase_propuesta', row.get('clase'))) for row in profile['rutas'])):
            report['estado'] = 'VALIDACION_TIPOS_COMPLETA_CON_PENDIENTES'
        else:
            report['estado'] = 'TIPOS_VERIFICADOS'
        emit(f"Modelo: {len(fields)} campos; tipos pendientes: {report['campos_tipo_pendiente']}; "
             f"campos con incidencias: {report['campos_con_incidencias']}.")
    except Exception as exc:
        failure = exc
        report['error'] = str(exc)
    report['fin_utc'] = dt.datetime.now(dt.timezone.utc).isoformat()
    write_reports(folder, report, profile)
    emit('Estado: ' + report['estado'])
    emit('Resultado JSON: ' + report['archivo_resultado'])
    if failure is not None:
        raise failure
    return folder, report
