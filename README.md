# Generador Sintético de Lista de Espera Quirúrgica

Herramientas para generar datasets sintéticos y clínicamente coherentes de listas de espera quirúrgicas españolas, usando códigos CIE-10-ES e ICD-10-PCS-ES reales.

---

## Estructura del proyecto

```
TFG/
├── datos/
│   ├── Diagnosticos_ES2026.csv        # Códigos CIE-10-ES de diagnósticos
│   └── Procedimientos_ES2026.csv      # Códigos ICD-10-PCS-ES de procedimientos
├── datos_generados/
│   ├── proc_embeddings.npy            # Caché de embeddings (generado por precalcular_embeddings.py)
│   ├── pacientes.csv                  # Datos identificativos (script original)
│   ├── lista_espera_quirurgica.csv    # Lista de espera completa (script original)
│   ├── pacientes1.csv                 # Datos identificativos (script OpenAI)
│   └── lista_espera_quirurgica1.csv   # Lista de espera completa (script OpenAI)
├── generar_lista_espera.py            # Generador original (grupos temáticos + Claude opcional)
├── generar_lista_espera_openai.py     # Generador con embeddings + OpenAI (gpt-4o-mini)
└── precalcular_embeddings.py          # Precalcula embeddings de procedimientos (ejecutar una vez)
```

---

## Script disponible

### `generar_lista_espera_openai.py` — Versión con embeddings + OpenAI

Versión más avanzada que reemplaza los grupos temáticos fijos por **búsqueda semántica por similitud coseno** para encontrar los procedimientos más relevantes para cada diagnóstico, y delega la selección final y la generación de todos los campos clínicos a **GPT-4o-mini en una sola llamada**.

```bash
python3 generar_lista_espera_openai.py [N]
```

Requiere: `OPENAI_API_KEY` + haber ejecutado `precalcular_embeddings.py` primero.

Salidas: `datos_generados/pacientes1.csv` y `datos_generados/lista_espera_quirurgica1.csv`.

---

### `precalcular_embeddings.py` — Paso previo obligatorio para la versión OpenAI

Descarga el modelo `paraphrase-multilingual-MiniLM-L12-v2` y calcula los embeddings de todos los procedimientos ICD-10-PCS, guardándolos en `datos_generados/proc_embeddings.npy`. Solo hay que ejecutarlo una vez.

```bash
python3 precalcular_embeddings.py
```

Si el fichero ya existe, el script no lo sobreescribe (hay que borrarlo manualmente para recalcular).

---

## Instalación

```bash
pip install openai anthropic sentence-transformers faker pandas numpy python-dotenv httpx
```

Variables de entorno necesarias (se pueden poner en un fichero `.env` en la raíz del proyecto):

```
OPENAI_API_KEY=sk-...       # Para generar_lista_espera_openai.py
ANTHROPIC_API_KEY=sk-ant-... # Para generar_lista_espera.py --ia
```

---

## Cómo funciona la versión OpenAI

1. **Selección de diagnósticos**: Se elige 1-3 diagnósticos del mismo capítulo ICD-10, respetando restricciones de sexo y edad (p. ej., capítulo O solo para mujeres; causas externas V/W/X/Y solo un diagnóstico).

2. **Búsqueda de procedimientos por similitud**: Se codifica el texto de los diagnósticos con `sentence-transformers` y se calcula la similitud coseno contra los embeddings precalculados de todos los procedimientos. Se seleccionan los 30 candidatos más relevantes.

3. **Llamada única a GPT-4o-mini**: Se envían los 30 candidatos junto con el perfil del paciente (edad, sexo, diagnósticos). El modelo elige el procedimiento más apropiado y genera los campos clínicos en JSON estructurado:
   - `tipo_cirugia` (Laparoscópica, Abierta, Robótica…)
   - `lateralidad` (Derecha, Izquierda, Bilateral, No aplica)
   - `observaciones`, `curso_clinico`, `intervenciones_previas`
   - `otros_parametros` (IMC, riesgo ASA, alergias)
   - `comorbilidades`

4. **Servicio médico**: Se asigna automáticamente por el capítulo ICD-10 del diagnóstico principal (sin intervención del LLM).

---

## Campos generados

### `lista_espera_quirurgica1.csv` (versión OpenAI)

| Campo | Descripción |
|---|---|
| `ID_Paciente` | UUID único |
| `Edad`, `Sexo`, `Prioridad` | Datos demográficos y prioridad (Preferente/Normal/Urgente) |
| `Codigo_Diagnostico_1/2/3` | Códigos CIE-10-ES (1 obligatorio, 2-3 opcionales) |
| `Descripcion_Diagnostico_1/2/3` | Descripciones de los diagnósticos |
| `Codigo_Procedimiento` | Código ICD-10-PCS-ES del procedimiento |
| `Descripcion_Procedimiento` | Descripción del procedimiento |
| `Tipo_Cirugia` | Técnica quirúrgica elegida por el LLM |
| `Servicio` | Especialidad médica (asignada por capítulo ICD-10) |
| `Lateralidad` | Derecha / Izquierda / Bilateral / No aplica |
| `Comorbilidades` | Enfermedades concomitantes coherentes con el caso |
| `Intervenciones_Previas` | Antecedentes quirúrgicos o "Ninguna" |
| `Curso_Clinico` | Narrativa de 2-3 frases del seguimiento en consulta |
| `Observaciones` | Alertas clínicas perioperatorias |
| `Otros_Parametros_Clinicos` | IMC, riesgo ASA, alergias conocidas |

---

## Consideraciones importantes

### Fallback ante errores de la API

Si una llamada a OpenAI falla, la versión OpenAI registra un aviso por consola y devuelve valores por defecto (campos vacíos o "Ninguna"). 

### El fichero `proc_embeddings.npy` no está en el repositorio

Es un fichero binario grande (~25-50 MB). Si no está presente, `generar_lista_espera_openai.py` lanzará `FileNotFoundError` con instrucciones claras. Hay que ejecutar `precalcular_embeddings.py` antes de la primera ejecución o tras cambiar el CSV de procedimientos.

### Restricciones de sexo en los datos de origen

Los CSVs de diagnósticos y procedimientos incluyen columnas `Hombre` y `Mujer`. Cuando una fila tiene `Mujer=1`, ese diagnóstico/procedimiento es exclusivo de mujeres (y viceversa).

## Flujo de trabajo recomendado

```bash
# 1. Solo la primera vez (o tras actualizar Procedimientos_ES2026.csv)
python3 precalcular_embeddings.py

# 2. Generar dataset sintético
python3 generar_lista_espera_openai.py 500

```
