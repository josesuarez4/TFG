# Cuadro de mando para la gestión de listas de espera quirúrgicas — TFG

Herramienta de generación de datos sintéticos y dashboard de gestión de lista de espera quirúrgica para un hospital español, usando códigos CIE-10-ES e ICD-10-PCS-ES reales.

---

## Estructura del proyecto

```
TFG/
├── datos/
│   ├── Diagnosticos_ES2026.csv               # Códigos CIE-10-ES de diagnósticos
│   └── Procedimientos_ES2026.csv             # Códigos ICD-10-PCS-ES de procedimientos
├── datos_generados/
│   ├── dashboard/
│   │   ├── lista_espera_quirurgica.csv        # Dato central del dashboard
│   │   ├── huecos_disponibles.csv             # Huecos generados por cancelaciones
│   │   ├── registro_planificacion.json        # Última planificación por servicio
│   │   ├── quirofanos_tarde.json              # Asignaciones de quirófanos de tarde
│   │   ├── dias_cerrados.csv                  # Días cerrados por quirófano
│   │   ├── especialistas_no_disponibles.csv   # Periodos de no disponibilidad
│   │   ├── cancelaciones.csv                  # Historial de cancelaciones
│   │   └── resultados_evaluacion.txt          # Resultados de la evaluación comparativa
│   └── generador/
│       ├── proc_embeddings.npy                # Caché de embeddings (generado una vez)
│       └── pacientes.csv                      # Datos identificativos generados
├── dashboard/
│   ├── dashboard.py
│   ├── planificador.py
│   ├── huecos.py
│   ├── cancelaciones.py
│   ├── restricciones.py
│   ├── quirofanos.py
│   ├── especialistas.py
│   ├── registro_planificacion.py
│   └── exportacion_pdf.py
├── generador/
│   ├── generar_lista_espera_rae.py
│   ├── generar_lista_espera_openai.py
│   ├── precalcular_embeddings.py
│   ├── filtro_procedimientos.py
│   └── rae_cmbd_pesos.py
├── evaluacion_comparativa.py
├── prioridad.py
└── tests/
```

---

## Instalación

```bash
pip install streamlit streamlit-extras streamlit-calendar plotly \
            pandas numpy faker sentence-transformers openai \
            fpdf2 python-dotenv httpx pytest pdoc
```

Variables de entorno (fichero `.env` en `generador/`):

```
OPENAI_API_KEY=sk-...
```

---

## Generador de datos

### Ejecución

**Paso previo — calcular embeddings (solo la primera vez):**

```bash
cd generador
python3 precalcular_embeddings.py
```

Descarga el modelo `paraphrase-multilingual-MiniLM-L12-v2` y calcula los embeddings de todos los procedimientos ICD-10-PCS, guardándolos en `datos_generados/generador/proc_embeddings.npy`. Si el fichero ya existe no se sobreescribe.

**Generar la lista de espera:**

```bash
cd generador
python3 generar_lista_espera_rae.py [N]   # N pacientes (por defecto 500)
```

Salidas:
- `datos_generados/generador/pacientes.csv` — datos identificativos
- `datos_generados/dashboard/lista_espera_quirurgica.csv` — lista de espera completa lista para el dashboard

### Módulos

**`generar_lista_espera_rae.py`** — Generador principal. `generate_dataset_rae()` produce cada paciente de forma secuencial usando los pesos epidemiológicos RAE-CMBD 2022 para seleccionar diagnóstico, edad y comorbilidades, y delega la generación de campos clínicos en `generar_lista_espera_openai.py`. Guarda checkpoints cada 500 pacientes para poder reanudar ante interrupciones.

**`generar_lista_espera_openai.py`** — Núcleo compartido del generador. `_procedure_candidates()` codifica el diagnóstico con `sentence-transformers` y calcula la similitud coseno contra los embeddings precalculados para seleccionar los 30 procedimientos más relevantes. `_generate_clinical_data()` envía esos candidatos a GPT-4o-mini y obtiene en JSON el procedimiento elegido y todos los campos clínicos. Ante fallos de la API aplica un fallback con valores por defecto para no interrumpir la generación. Los campos identificativos del paciente (`Nombre_Apellidos`, `Medico_Peticionario`) no se generan para evitar datos PII innecesarios.

**`precalcular_embeddings.py`** — Descarga el modelo `paraphrase-multilingual-MiniLM-L12-v2` y calcula los embeddings de todos los procedimientos ICD-10-PCS con normalización L2, guardándolos en `proc_embeddings.npy`. Si el fichero ya existe no lo sobreescribe.

**`filtro_procedimientos.py`** — `filter_surgical_procedures()` filtra el CSV de procedimientos para quedarse únicamente con los de la sección 0 del ICD-10-PCS (procedimientos quirúrgicos médico-quirúrgicos), descartando las secciones de imagen, rehabilitación u otros.

**`rae_cmbd_pesos.py`** — Contiene las funciones `select_diagnosis_rae()`, `sample_age_rae()` y `sample_comorbidities_rae()`, que muestrean diagnóstico, edad y comorbilidades según los pesos de prevalencia extraídos del informe RAE-CMBD 2022, garantizando una distribución epidemiológicamente coherente con la realidad hospitalaria española.

### Cómo funciona

1. **Selección de diagnóstico**: se elige según los pesos de prevalencia RAE-CMBD 2022, respetando restricciones de sexo y edad.
2. **Búsqueda de procedimiento**: se codifica el diagnóstico con `sentence-transformers` y se calcula la similitud coseno contra los embeddings precalculados. Se seleccionan los 30 candidatos más relevantes.
3. **Generación clínica**: GPT-4o-mini recibe los candidatos y el perfil del paciente y devuelve en JSON el procedimiento elegido y todos los campos clínicos (tipo de cirugía, lateralidad, comorbilidades, curso clínico, etc.).
4. **Asignación de servicio**: se asigna automáticamente por el capítulo ICD-10 del diagnóstico, sin intervención del modelo.

---

## Dashboard

### Ejecución

```bash
cd dashboard
streamlit run dashboard.py
```

El dashboard se abre en el navegador en `http://localhost:8501`. Lee `datos_generados/dashboard/lista_espera_quirurgica.csv` como fuente de datos principal.

### Módulos

**`dashboard.py`** — Punto de entrada. Gestiona la interfaz, el estado de sesión y coordina el resto de módulos. Usa `@st.cache_data` con invalidación por `mtime` del CSV para evitar recargas innecesarias, y el patrón `st.session_state.pop()` para mostrar mensajes de confirmación que sobreviven a un `st.rerun()`.

**`planificador.py`** — Núcleo del algoritmo de planificación. La función `_assign_slot()` busca el primer hueco libre en los quirófanos del servicio comprobando solapamientos con cirugías ya asignadas y periodos de no disponibilidad de especialistas, incluyendo el tiempo de rotación entre intervenciones. `service_planning()` ordena los pacientes por prioridad y llama a `_assign_slot()` para cada uno dentro de la ventana de fechas indicada. `find_free_slots()` realiza la misma búsqueda para asignaciones manuales o reasignaciones tras cancelación. `compute_pm_impact()` simula cuatro semanas de planificación por servicio para estimar qué servicio se beneficiaría más de un quirófano de tarde.

**`prioridad.py`** — Calcula la puntuación de prioridad (0–100) de cada paciente con la fórmula `espera·0,40 + edad·0,35 + invasividad·0,25`. El componente de edad aplica una curva en V asimétrica con vértice en los 35 años (suelo de 15 puntos), de modo que la prioridad crece tanto hacia edades muy jóvenes como hacia edades avanzadas. El componente de invasividad asigna un peso fijo por tipo de cirugía (abierta en el extremo alto, percutánea y endoscópica en el bajo).

**`huecos.py`** — Gestiona el ciclo de vida de los huecos generados por cancelaciones. `procedure_similarity()` calcula la similitud entre dos códigos ICD-10-PCS ponderando cada posición del código (sección, sistema, operación…) con un peso distinto. `find_candidates()` filtra pacientes elegibles del mismo servicio y los puntúa combinando prioridad (60 %) y similitud de procedimiento (40 %), con soporte de paginación.

**`restricciones.py`** — Carga y persiste los días cerrados de quirófanos y los periodos de no disponibilidad de especialistas desde los CSV correspondientes. Expone `load_closed_days()` y `load_unavailable_specs()`, que devuelven estructuras indexadas por quirófano y especialista respectivamente para consulta eficiente durante la planificación.

**`quirofanos.py`** — Define el diccionario `ROOMS_BY_SERVICE` con los quirófanos asignados a cada servicio. Gestiona los quirófanos de tarde mediante una lista de asignaciones con rango de fechas; `load_pm_assignment(fecha)` devuelve solo las activas en esa fecha, `find_pm_for_service_in_range(service, start, end)` devuelve el quirófano de tarde activo en la ventana de planificación, `has_pm_overlap()` impide guardar rangos solapados para el mismo quirófano y `has_service_overlap()` impide que un mismo servicio tenga dos quirófanos de tarde asignados simultáneamente.

**`registro_planificacion.py`** — Persiste la fecha de fin de la última planificación por servicio en `registro_planificacion.json`. `get_reference_date()` devuelve el día siguiente al último horizonte planificado (o hoy si nunca se ha planificado), garantizando que los ciclos consecutivos no dejen huecos temporales.

**`cancelaciones.py`** — Registra el historial de cancelaciones de citas quirúrgicas en `cancelaciones.csv`. `save_cancellation()` añade una fila por cada cancelación con la fecha, el servicio, el identificador del paciente y el motivo. `load_cancellations()` devuelve el historial completo como DataFrame, permitiendo calcular en el tab de análisis los KPIs de cancelaciones totales por servicio, cancelaciones en el mes en curso, porcentaje sobre intervenciones programadas y motivo más frecuente.

**`especialistas.py`** — Contiene el diccionario `SPECIALISTS_BY_ROOM` con los especialistas asignados a cada quirófano, su jornada (hora de inicio y fin) y los días laborables de la semana. `specialists_for_service()` devuelve la lista de especialistas de todos los quirófanos de un servicio, incluyendo el quirófano de tarde si está asignado.

**`exportacion_pdf.py`** — Genera mediante `fpdf2` el informe PDF de la planificación quirúrgica de un servicio en un rango de fechas, con una tabla por día que lista los pacientes asignados, quirófano, hora y duración estimada.

---

## Evaluación comparativa

```bash
python3 evaluacion_comparativa.py
```

Simula 12 semanas de planificación con dos estrategias (prioridad vs. FIFO) y guarda los resultados en `datos_generados/generador/resultados_evaluacion.txt`.

---

## Tests

La suite de tests cubre los módulos de lógica de negocio del dashboard con 84 tests unitarios usando `pytest` y `unittest.mock`. Los ficheros de datos se sustituyen por DataFrames en memoria mediante `patch.object`, de forma que los tests no dependen del sistema de ficheros.

```bash
python3 -m pytest tests/ -v
```

| Fichero | Módulo bajo test | Tests |
|---|---|---|
| `test_prioridad.py` | `prioridad.py` | 9 |
| `test_planificador.py` | `planificador.py` | 14 |
| `test_planificacion_servicio.py` | `planificador.py` | 12 |
| `test_huecos.py` | `huecos.py` | 25 |
| `test_restricciones.py` | `restricciones.py` | 11 |
| `test_registro_planificacion.py` | `registro_planificacion.py` | 8 |

---

## Documentación

La documentación de los módulos del dashboard se genera automáticamente a partir de los docstrings con `pdoc`:

```bash
pdoc dashboard/ -o docs/
```

Los ficheros HTML resultantes se guardan en `docs/` (excluido del repositorio por `.gitignore`).
