import pandas as pd
import os
from difflib import SequenceMatcher

def buscar_codigos_por_similitud(operacion, df_codigos, umbral=0.3):
    """
    Busca todos los códigos apropiados para una operación comparando
    con las descripciones de enfermedades en el archivo de códigos.
    
    Parámetros:
    - operacion: nombre de la operación quirúrgica
    - df_codigos: DataFrame con códigos y descripciones
    - umbral: umbral mínimo de similitud (0.0 a 1.0)
    
    Retorna: lista de tuplas (código, descripción, puntuación)
    """
    coincidencias = []
    
    operacion_lower = operacion.lower()
    
    # Diccionario de términos clave para mejorar la búsqueda
    terminos_relacionados = {
        # Operaciones ortopédicas
        'artroscopia de rodilla': ['rodilla', 'menisc', 'gonartrosis'],
        'prótesis de cadera': ['coxartrosis', 'cadera'],
        'prótesis de rodilla': ['gonartrosis', 'rodilla'],
        'meniscectomía': ['menisc', 'rodilla'],
        'fijación de fracturas': ['fractura'],
        'cirugía de columna': ['columna', 'hernia', 'disco', 'vértebra'],
        'prótesis de hombro': ['hombro', 'artrosis'],
        'reparación de ligamento cruzado': ['rodilla', 'ligamento'],
        
        # Operaciones oftalmológicas
        'cataratas': ['catarata'],
        'cirugía de glaucoma': ['glaucoma'],
        'cirugía de retina': ['retina', 'infarto retiniano'],
        'corrección de estrabismo': ['strabismus', 'estrabismo'],
        
        # Operaciones cardiovasculares
        'bypass coronario': ['coronariopatía', 'coronario', 'infarto'],
        'angioplastia': ['coronariopatía', 'coronario', 'isquémica', 'infarto'],
        'marcapasos': ['arritmia', 'taquicardia', 'fibrilación', 'conducción cardiaca'],
        'reparación de válvula cardíaca': ['endocarditis', 'válvula'],
        'cirugía de aneurisma': ['aneurisma', 'vascular'],
        
        # Operaciones gastrointestinales
        'apendicectomía': ['apendic'],
        'colecistectomía': ['coleliti', 'colecist', 'biliar'],
        'hernias': ['hernia'],
        'gastrectomía': ['gástrica', 'úlcera', 'estómago'],
        'cirugía de colon': ['colitis', 'colon', 'crohn'],
        'cirugía de úlcera gástrica': ['úlcera gástrica'],
        
        # Operaciones ginecológicas y obstétricas
        'histerectomía': ['útero', 'uterino'],
        'cesárea': ['cesárea'],
        'cirugía de ovarios': ['ovario', 'endometriosis'],
        'miomectomía': ['útero', 'uterino'],
        
        # Operaciones urológicas
        'próstata': ['próstata'],
        'litotricia renal': ['renal', 'riñón'],
        'cistectomía': ['cistitis', 'vesical'],
        'vasectomía': ['testículo'],
        
        # Operaciones otorrinolaringológicas
        'amigdalectomía': ['amigdal', 'amígdal'],
        'cirugía de senos paranasales': ['sinusitis'],
        'septoplastia': ['nasal'],
        'cirugía de oído medio': ['otitis', 'oído'],
        
        # Operaciones de cirugía general
        'cirugía de tiroides': ['tiroide', 'bocio'],
        'cirugía de túnel carpiano': ['túnel carpiano', 'carpiano'],
        'varices': ['varic', 'vena'],
        'mastectomía': ['mama', 'cáncer de mama'],
        'biopsia de mama': ['mama', 'neoplasia'],
        
        # Operaciones neurológicas
        'craneotomía': ['craneal', 'cerebral', 'intracraneal'],
        'cirugía de hernia discal': ['disco', 'hernia', 'lumbar'],
        'derivación ventricular': ['hidrocefalia', 'ventricular'],
        
        # Operaciones torácicas
        'cirugía de pulmón': ['pulmonar', 'pulmón', 'cáncer', 'bronquios'],
        'toracotomía': ['torácica', 'pulmón'],
        
        # Otras operaciones especializadas
        'cirugía bariátrica': ['obesidad'],
        'trasplante renal': ['renal', 'riñón'],
        'cirugía de melanoma': ['melanoma'],
    }
    
    # Obtener términos para esta operación
    terminos = terminos_relacionados.get(operacion_lower, [operacion_lower.split()[0]])
    
    for _, row in df_codigos.iterrows():
        codigo = row['Código']
        descripcion = str(row['Descripción']).lower()
        
        # Calcular puntuación basada en coincidencias de términos
        puntuacion = 0
        for termino in terminos:
            if termino in descripcion:
                puntuacion += 1.0
            else:
                # Usar similitud de secuencia como respaldo
                similitud = SequenceMatcher(None, termino, descripcion).ratio()
                puntuacion += similitud * 0.5
        
        # Normalizar puntuación
        puntuacion = puntuacion / len(terminos) if terminos else 0
        
        if puntuacion >= umbral:
            coincidencias.append((codigo, row['Descripción'], puntuacion))
    
    # Ordenar por puntuación descendente
    coincidencias.sort(key=lambda x: x[2], reverse=True)
    
    return coincidencias


def agregar_codigos_a_lista():
    """
    Programa que agrega códigos de enfermedad a la lista simulada.
    Busca automáticamente en el archivo de códigos las mejores coincidencias
    entre operaciones y enfermedades.
    """
    
    # Rutas de los archivos
    ruta_base = os.path.dirname(os.path.dirname(__file__))
    ruta_codigos = os.path.join(ruta_base, 'Datos', 'Codigo_enfermedad.csv')
    ruta_lista = os.path.join(ruta_base, 'Datos', 'lista_simulada.csv')
    ruta_salida = os.path.join(ruta_base, 'Datos', 'lista_con_codigo.csv')
    
    # Leer los archivos CSV
    print("Leyendo archivos...")
    # Leer el archivo de códigos manejando comas en las descripciones
    # Solo dividir por la primera coma
    codigos_data = []
    with open(ruta_codigos, 'r', encoding='utf-8') as f:
        lines = f.readlines()[1:]  # Saltar encabezado
        for line in lines:
            line = line.strip()
            if line:
                # Dividir solo por la primera coma
                parts = line.split(',', 1)
                if len(parts) == 2:
                    codigos_data.append({'Código': parts[0], 'Descripción': parts[1]})
    
    df_codigos = pd.DataFrame(codigos_data)
    df_lista = pd.read_csv(ruta_lista)
    
    print(f"Códigos de enfermedad: {len(df_codigos)} registros")
    print(f"Lista: {len(df_lista)} registros")
    
    # Obtener las operaciones únicas
    operaciones_unicas = df_lista['operacion'].unique()
    print(f"\nOperaciones únicas encontradas: {len(operaciones_unicas)}")
    
    # Buscar códigos automáticamente para cada operación
    print("\nBuscando códigos en el archivo de enfermedades...")
    mapeo_operacion_codigo = {}
    
    for operacion in sorted(operaciones_unicas):
        coincidencias = buscar_codigos_por_similitud(operacion, df_codigos)
        if coincidencias:
            # Guardar todos los códigos separados por punto y coma
            codigos = ';'.join([c[0] for c in coincidencias])
            mapeo_operacion_codigo[operacion] = codigos
            
            print(f"\n  {operacion}:")
            for codigo, descripcion, puntuacion in coincidencias:
                print(f"    → {codigo:8s} | {descripcion} (similitud: {puntuacion:.2f})")
        else:
            print(f"\n  ✗ {operacion} → No se encontró coincidencia")
    
    # Verificar si todas las operaciones tienen un código asignado
    operaciones_sin_codigo = [op for op in operaciones_unicas if op not in mapeo_operacion_codigo]
    if operaciones_sin_codigo:
        print(f"\n⚠ ADVERTENCIA: Las siguientes operaciones no tienen código asignado:")
        for op in operaciones_sin_codigo:
            print(f"  - {op}")
    
    # Agregar la columna de código
    print("\nAgregando columna de código...")
    df_lista['codigo'] = df_lista['operacion'].map(mapeo_operacion_codigo)
    
    # Reordenar las columnas para que el código esté después de la operación
    columnas = ['paciente_id', 'hospital', 'operacion', 'codigo', 'prioridad', 
                'fecha_entrada', 'fecha_intervencion', 'estado']
    df_lista = df_lista[columnas]
    
    # Guardar el resultado
    df_lista.to_csv(ruta_salida, index=False)
    print(f"\n✓ Archivo generado exitosamente: {ruta_salida}")
    print(f"  Total de registros: {len(df_lista)}")
    
    # Mostrar estadísticas
    print("\nEstadísticas por operación:")
    for operacion in sorted(operaciones_unicas):
        count = len(df_lista[df_lista['operacion'] == operacion])
        codigos = mapeo_operacion_codigo.get(operacion, 'Sin código')
        num_codigos = len(codigos.split(';')) if codigos != 'Sin código' else 0
        print(f"  {operacion}: {count} pacientes → {num_codigos} código(s) asignado(s)")
    
    # Mostrar las primeras filas del resultado
    print("\nPrimeras 10 filas del resultado:")
    print(df_lista.head(10).to_string(index=False))
    
    return df_lista


if __name__ == "__main__":
    print("=" * 70)
    print("PROGRAMA PARA AGREGAR CÓDIGOS A LA LISTA")
    print("=" * 70)
    
    df_resultado = agregar_codigos_a_lista()
    
    print("\n" + "=" * 70)
    print("PROCESO COMPLETADO")
    print("=" * 70)
