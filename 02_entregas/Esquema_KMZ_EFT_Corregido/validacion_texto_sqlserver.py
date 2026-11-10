"""Consulta metadatos SQL Server para la unica ampliacion TEXT aprobada.

Todas las consultas son SELECT a catalogos del sistema. Las escrituras se
realizan con herramientas ArcGIS fuera de este modulo.
"""
import re


ALLOWED_FIELDS = frozenset(('cargas_y_gravamenes', 'tmp_cargas_y_gravamenes_151',
                            'bak_cargas_y_gravamenes_151'))
ALLOWED_TABLES = frozenset(('predios_inscritos_en_sunarp_recorte',
                          'predios_inscritos_sunarp_recorte'))


def verify(a,workspace,owner,require_max=False,field_name='cargas_y_gravamenes',
           table_name='predios_inscritos_sunarp_recorte'):
    if field_name not in ALLOWED_FIELDS:
        raise ValueError('Campo no autorizado para verificar el texto largo.')
    if table_name not in ALLOWED_TABLES:
        raise ValueError('Clase no autorizada para verificar el texto largo.')
    if not str(workspace).lower().endswith('.sde'):
        return None
    if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',owner):
        raise ValueError('Propietario invalido para verificar el texto largo.')
    sql=("SELECT ty.name, col.max_length FROM sys.columns AS col "
         "JOIN sys.tables AS tab ON tab.object_id=col.object_id "
         "JOIN sys.schemas AS sch ON sch.schema_id=tab.schema_id "
         "JOIN sys.types AS ty ON ty.user_type_id=col.user_type_id "
         f"WHERE LOWER(sch.name)=LOWER(N'{owner}') "
         f"AND LOWER(tab.name)=N'{table_name}' "
         f"AND LOWER(col.name)=N'{field_name}'")
    connection=a.ArcSDESQLExecute(str(workspace))
    result=connection.execute(sql)
    if not isinstance(result,list) or len(result)!=1 or len(result[0])!=2:
        raise ValueError(f'No se pudo identificar exactamente una columna {field_name} en los metadatos de SQL Server.')
    datatype=str(result[0][0]).lower()
    length=int(result[0][1])
    if datatype!='nvarchar':
        raise ValueError(f'{field_name} usa {datatype}; se requiere NVARCHAR para preservar Unicode. Revisar UNICODE_STRING con el administrador antes de ampliar.')
    if require_max and length!=-1:
        raise ValueError(f'{field_name} no se confirma como NVARCHAR(MAX): max_length={length}. Se detiene para revision.')
    return dict(tipo_sql=datatype,max_length_bytes=length,unicode=True,es_max=length==-1)
