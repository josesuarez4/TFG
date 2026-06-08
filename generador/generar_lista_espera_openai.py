import json
import os
import random
import re
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # permite importar prioridad.py desde la raíz

from proc_filter import filter_surgical_procedures

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

import httpx
import numpy as np
import pandas as pd
from faker import Faker
from openai import OpenAI
from sentence_transformers import SentenceTransformer

BASE_DIR       = Path(__file__).parent.parent
DATA_DIR       = BASE_DIR / "datos"
CACHE_DIR      = BASE_DIR / "datos_generados"

OPENAI_MODEL       = "gpt-4o-mini"
OPENAI_MAX_TOKENS  = 500
OPENAI_TEMPERATURE = 0.7
EMBEDDING_MODEL    = "paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDINGS_CACHE   = CACHE_DIR / "proc_embeddings.npy"
N_CANDIDATES       = 30

TIPO_CIRUGIA_OPTIONS = [
    "Laparoscópica", "Artroscópica", "Abierta", "Endoscópica",
    "Robótica", "Mínimamente invasiva", "Percutánea", "No aplica",
]
LATERALIDAD_OPTIONS = ["Derecha", "Izquierda", "Bilateral", "No aplica"]

_CLINICAL_FALLBACK: dict = {
    "numero_procedimiento":  0,
    "tipo_cirugia":          TIPO_CIRUGIA_OPTIONS[2],   # Abierta
    "lateralidad":           LATERALIDAD_OPTIONS[-1],   # No aplica
    "anatomia_principal":    "",
    "procedimiento_correcto": True,
    "observaciones":         "",
    "curso_clinico":         "",
    "intervenciones_previas": "Ninguna",
    "otros_parametros":      "",
    "comorbilidades":        "Ninguna",
}

# Capítulo ICD-10 → sistemas orgánicos ICD-10-PCS permitidos
_DIAG_TO_PROC_SYSTEMS: dict[str, frozenset[str]] = {
    'A': frozenset({'D', 'F', 'H', 'J', 'W'}),
    'B': frozenset({'D', 'F', 'H', 'J', 'W'}),
    'E': frozenset({'G'}),
    'G': frozenset({'0', '1'}),
    'I': frozenset({'2', '3', '4', '5', '6'}),
    'L': frozenset({'H', 'J'}),
    'M': frozenset({'K', 'L', 'M', 'N', 'P', 'Q', 'R', 'S', 'X', 'Y'}),
    'N': frozenset({'T', 'U', 'V'}),
    'O': frozenset({'U'}),
    'P': frozenset({'D', 'F', 'W', '2'}),
}

_K_SUBSYSTEMS: list[tuple[tuple[str, str], frozenset[str]]] = [
    (("K00", "K31"), frozenset({'C', 'D', 'W'})),
    (("K35", "K68"), frozenset({'D', 'W'})),
    (("K70", "K95"), frozenset({'F'})),
]

_C_SUBSYSTEMS: list[tuple[tuple[str, str], frozenset[str]]] = [
    (("C00", "C39"), frozenset({'C', 'D', 'F', 'B', '9', 'N', 'P', 'Q'})),
    (("C40", "C75"), frozenset({'H', 'J', 'K', 'T', 'U', 'V', 'G', '0', '1', '8'})),
    (("C76", "C96"), frozenset({'W', '7'})),
]

_D_SUBSYSTEMS: list[tuple[tuple[str, str], frozenset[str]]] = [
    (("D00", "D48"), frozenset({'C', 'D', 'F', 'H', 'B', 'T', 'U', 'V', 'G', '8', '9', '7', 'W'})),
    (("D50", "D89"), frozenset({'7'})),
]

_Q_SUBSYSTEMS: list[tuple[tuple[str, str], frozenset[str]]] = [
    (("Q00", "Q28"), frozenset({'0', '1', '8', '9', 'N', '2', '3', '4', '5', '6'})),
    (("Q30", "Q64"), frozenset({'B', 'C', 'D', 'F', 'W', 'T', 'U', 'V', '9'})),
    (("Q65", "Q89"), frozenset({'K', 'L', 'M', 'N', 'P', 'Q', 'R', 'S', 'X', 'Y', 'H', 'J', 'W'})),
]

_S_HEAD_TRUNK_SUBSYSTEMS: list[tuple[tuple[str, str], frozenset[str]]] = [
    (("S00", "S19"), frozenset({'0', '1', 'N', 'P', '8', '9'})),
    (("S20", "S39"), frozenset({'B', '2', 'D', 'F', 'T', 'U', 'V', 'W', 'P', 'Q'})),
]

_S_EXTREMITY_SYSTEMS: frozenset[str] = frozenset({'K', 'L', 'M', 'P', 'Q', 'R', 'S', 'X', 'Y'})

_T_SUBSYSTEMS: list[tuple[tuple[str, str], frozenset[str]]] = [
    (("T07", "T19"), frozenset({'W', '8', '9', 'B', 'C', 'D', 'T', 'U', 'V', 'J'})),
    (("T20", "T35"), frozenset({'H', 'J', 'W'})),
    (("T79", "T88"), frozenset({'W', 'D', 'B', 'T', 'K', 'L', 'M'})),
]


def _lookup_sub(
    sub: str,
    table: list[tuple[tuple[str, str], frozenset[str]]],
    fallback: frozenset[str] = frozenset({'W'}),
) -> frozenset[str]:
    for (start, end), systems in table:
        if start[1:] <= sub <= end[1:]:
            return systems
    return fallback


def _get_proc_systems(diag_code: str) -> frozenset[str]:
    """Sistemas ICD-10-PCS válidos para el diagnóstico. frozenset vacío = sin filtro."""
    if not diag_code:
        return frozenset()
    chapter = diag_code[0]
    sub     = diag_code[1:3] if len(diag_code) >= 3 else ""

    if chapter == 'H':
        return frozenset({'8'}) if sub <= '59' else frozenset({'9'})
    if chapter == 'J':
        return frozenset({'9', 'C'}) if (sub <= '06' or '30' <= sub <= '39') else frozenset({'B'})
    if chapter == 'K':
        return _lookup_sub(sub, _K_SUBSYSTEMS, frozenset({'D', 'W'}))
    if chapter == 'C':
        return _lookup_sub(sub, _C_SUBSYSTEMS)
    if chapter == 'D':
        return _lookup_sub(sub, _D_SUBSYSTEMS)
    if chapter == 'Q':
        return _lookup_sub(sub, _Q_SUBSYSTEMS)
    if chapter == 'S':
        return _S_EXTREMITY_SYSTEMS if '40' <= sub <= '99' else _lookup_sub(sub, _S_HEAD_TRUNK_SUBSYSTEMS)
    if chapter == 'T':
        return _lookup_sub(sub, _T_SUBSYSTEMS)

    direct = _DIAG_TO_PROC_SYSTEMS.get(chapter)
    return direct if direct is not None else frozenset()


# Abordaje ICD-10-PCS (índice 4) → tipo de cirugía
_APPROACH_TIPO: dict[str, str] = {
    '0': "Abierta",
    '3': "Percutánea",
    '7': "Endoscópica",
    '8': "Endoscópica",
    'X': "No aplica",
}
_APPROACH_4_VALID: frozenset[str] = frozenset({
    "Laparoscópica", "Artroscópica", "Robótica", "Endoscópica", "Mínimamente invasiva",
})

# Patrones de sexo en descripciones (segunda línea de defensa tras flags CSV)
_MALE_DESC_RE   = re.compile(r"\bmasculin[ao]?\b", re.IGNORECASE)
_FEMALE_DESC_RE = re.compile(
    r"\bfemenin[ao]?\b|\bmatern[ao]?\b|\bembaraz"
    r"|\bovario\b|\bvagina\b|\bvulva\b|\b[uú]terin[ao]?\b"
    r"|\bfalopio\b|\bendometri|\bplacenta\b",
    re.IGNORECASE,
)

# Lateralidad
_LAT_DESC_RE  = re.compile(r"\b(derecho|derecha|izquierdo|izquierda|bilateral)\b", re.IGNORECASE)
_LAT_LEFT_RE  = re.compile(r"\bizquierd[ao]\b", re.IGNORECASE)
_LAT_RIGHT_RE = re.compile(r"\bderech[ao]\b",   re.IGNORECASE)

# Partes del tronco: excluye procedimientos troncales para diagnósticos de extremidad
_TRUNK_DESC_RE = re.compile(
    r"\b(?:tórax|torax|abdom(?:en|inal)|pelv(?:is|ico|iana?)|"
    r"columna|vértebra|vertebra|lumbar|sacr[oa]|coccígeo|coccigeo|"
    r"costilla|esternón|esternon|mediastino|diafragma)\b",
    re.IGNORECASE,
)


def _norm_laterality(term: str) -> str:
    t = term.lower()
    if "derech"   in t: return "Derecha"
    if "izquierd" in t: return "Izquierda"
    return "Bilateral"


def _extract_laterality(desc_proc: str, llm_lat: str) -> str:
    """Lateralidad desde la descripción ICD-10-PCS; si no aparece, usa el valor del LLM."""
    m = _LAT_DESC_RE.search(desc_proc)
    return _norm_laterality(m.group(1)) if m else llm_lat


def _fix_procedure_side(diags: list[pd.Series], candidates: pd.DataFrame, proc_idx: int) -> int:
    """Si el procedimiento tiene el lado contrario al diagnóstico, busca uno compatible en el pool."""
    if not diags:
        return proc_idx

    m_diag = _LAT_DESC_RE.search(diags[0]["Descripción"])
    if not m_diag:
        return proc_idx
    lat_diag = _norm_laterality(m_diag.group(1))
    if lat_diag == "Bilateral":
        return proc_idx

    m_proc = _LAT_DESC_RE.search(candidates.iloc[proc_idx]["Descripción"])
    if not m_proc:
        return proc_idx
    lat_proc = _norm_laterality(m_proc.group(1))
    if lat_proc == "Bilateral" or lat_proc == lat_diag:
        return proc_idx

    for i, row in candidates.iterrows():
        if i == proc_idx:
            continue
        m = _LAT_DESC_RE.search(row["Descripción"])
        if m and _norm_laterality(m.group(1)) == lat_diag:
            return i

    return proc_idx


def _fix_surgery_type(codigo_proc: str, llm_tipo: str) -> str:
    """Corrige el tipo de cirugía según el carácter de abordaje del código ICD-10-PCS."""
    if len(codigo_proc) < 5:
        return llm_tipo
    approach = codigo_proc[4]
    override = _APPROACH_TIPO.get(approach)
    if override:
        return override
    if approach == '4' and llm_tipo not in _APPROACH_4_VALID:
        return "Endoscópica"
    return llm_tipo


fake = Faker("es_ES")

_openai_client: OpenAI | None = None


def _get_openai_client() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise EnvironmentError(
                "No se encontró OPENAI_API_KEY.\n"
                "Windows: set OPENAI_API_KEY=sk-...\n"
                "Linux:   export OPENAI_API_KEY=sk-..."
            )
        _openai_client = OpenAI(api_key=api_key, http_client=httpx.Client(verify=False))
    return _openai_client


def _load_csv() -> tuple[pd.DataFrame, pd.DataFrame]:
    diag_raw = pd.read_csv(DATA_DIR / "Diagnosticos_ES2026.csv", dtype=str)
    proc_raw = pd.read_csv(DATA_DIR / "Procedimientos_ES2026.csv", dtype=str)

    leaf_pattern = re.compile(r"^[A-Z]\d{2}(\.\d+)?$")
    diag = diag_raw[diag_raw["Código"].str.match(leaf_pattern, na=False)].copy()

    # Eliminar categorías generales que tienen subcódigos más específicos
    codes_set = set(diag["Código"])
    diag = diag[diag["Código"].apply(
        lambda c: not any(other.startswith(c + ".") for other in codes_set)
    )]

    # Excluir F (trastornos mentales), V-Y (causas externas), Z (administrativos)
    diag = diag[~diag["Código"].str[0].isin(["F", "V", "W", "X", "Y"])]

    # Excluir intoxicaciones sin indicación quirúrgica (T36–T78)
    diag = diag[~(
        (diag["Código"].str[0] == "T") &
        (diag["Código"].str[1:3].between("36", "78"))
    )]

    # Excluir localizaciones anatómicas vagas
    _LOC_VAGA = r"otra localización|cualquier localización|localización no especificada|lugar no especificado"
    diag = diag[~diag["Descripción"].str.contains(_LOC_VAGA, case=False, na=False, regex=True)]

    proc = filter_surgical_procedures(proc_raw)

    diag.reset_index(drop=True, inplace=True)
    proc.reset_index(drop=True, inplace=True)
    return diag, proc


DIAG_DF, PROC_DF = _load_csv()

_model: SentenceTransformer | None = None
_proc_embeddings: np.ndarray | None = None


def _get_embedding_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _get_procedure_embeddings() -> np.ndarray:
    global _proc_embeddings
    if _proc_embeddings is None:
        if not EMBEDDINGS_CACHE.exists():
            raise FileNotFoundError(
                f"Cache no encontrado: '{EMBEDDINGS_CACHE}'.\n"
                "Ejecuta primero: python precalcular_embeddings.py"
            )
        _proc_embeddings = np.load(EMBEDDINGS_CACHE)
    return _proc_embeddings


# Sistema orgánico ICD-10-PCS (carácter 2) → servicio quirúrgico
_BODY_SYSTEM_SERVICE: dict[str, str] = {
    '0': 'Neurocirugía',                            # SNC y Nervios Craneales
    '1': 'Neurocirugía',                            # Sistema Nervioso Periférico
    '2': 'Cirugía Cardiovascular',                  # Corazón y Grandes Vasos
    '3': 'Angiología y Cirugía Vascular',           # Arterias Superiores
    '4': 'Angiología y Cirugía Vascular',           # Arterias Inferiores
    '5': 'Angiología y Cirugía Vascular',           # Venas Superiores
    '6': 'Angiología y Cirugía Vascular',           # Venas Inferiores
    '7': 'Cirugía General y Aparato Digestivo',     # Linfático y Hemático
    '8': 'Oftalmología',                            # Ojo
    '9': 'Otorrinolaringología',                    # Oído, Nariz, Senos
    'B': 'Cirugía Torácica',                        # Respiratorio
    'C': 'Cirugía Maxilofacial',                    # Boca y Garganta
    'D': 'Cirugía General y Aparato Digestivo',     # Gastrointestinal
    'F': 'Cirugía General y Aparato Digestivo',     # Hepatobiliar y Páncreas
    'G': 'Cirugía General y Aparato Digestivo',     # Endocrino
    'H': 'Dermatología',                            # Piel y Mama
    'J': 'Cirugía Plástica',                        # Tejido Subcutáneo y Fascia
    'K': 'Traumatología y Cirugía Ortopédica',      # Músculos
    'L': 'Traumatología y Cirugía Ortopédica',      # Tendones
    'M': 'Traumatología y Cirugía Ortopédica',      # Bursas y Ligamentos
    'N': 'Cirugía Maxilofacial',                    # Huesos Cráneo y Cara
    'P': 'Traumatología y Cirugía Ortopédica',      # Huesos Superiores
    'Q': 'Traumatología y Cirugía Ortopédica',      # Huesos Inferiores
    'R': 'Traumatología y Cirugía Ortopédica',      # Articulaciones Superiores
    'S': 'Traumatología y Cirugía Ortopédica',      # Articulaciones Inferiores
    'T': 'Urología',                                # Urinario
    'U': 'Ginecología y Obstetricia',               # Reproductor Femenino
    'V': 'Urología',                                # Reproductor Masculino
    'W': 'Cirugía General y Aparato Digestivo',     # Regiones Anatómicas Generales
    'X': 'Traumatología y Cirugía Ortopédica',      # Extremidades Superiores
    'Y': 'Traumatología y Cirugía Ortopédica',      # Extremidades Inferiores
}

_PROC_SECTION_SERVICE: dict[str, str] = {
    'X': 'Cirugía General y Aparato Digestivo',
}


def service_by_procedure(codigo: str) -> str:
    if not codigo or len(codigo) < 2:
        return 'Cirugía General y Aparato Digestivo'
    sec = codigo[0]
    if sec != '0':
        return _PROC_SECTION_SERVICE.get(sec, 'Cirugía General y Aparato Digestivo')
    return _BODY_SYSTEM_SERVICE.get(codigo[1], 'Cirugía General y Aparato Digestivo')


from prioridad import calculate_priority


def _patient_data() -> tuple[str, int, str]:
    sex        = random.choice(["Hombre", "Mujer"])
    birth_date = fake.date_of_birth(minimum_age=18, maximum_age=90)
    today      = date.today()
    age        = today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )
    return birth_date.isoformat(), age, sex


def _full_name(sex: str) -> str:
    fn = fake.first_name_male if sex == "Hombre" else fake.first_name_female
    return f"{fn()} {fake.last_name()} {fake.last_name()}"


def _doctor() -> str:
    title = random.choice(["Dr.", "Dra."])
    return f"{title} {fake.last_name()}, {fake.first_name()}"


def _select_diagnoses(sex: str, age: int) -> list[pd.Series]:
    candidates = DIAG_DF[DIAG_DF["Mujer"] != "1"] if sex == "Hombre" else DIAG_DF[DIAG_DF["Hombre"] != "1"]
    if sex == "Hombre":
        candidates = candidates[candidates["Código"].str[0] != "O"]
        candidates = candidates[~candidates["Descripción"].str.contains(_FEMALE_DESC_RE, na=False)]
    else:
        candidates = candidates[~candidates["Descripción"].str.contains(_MALE_DESC_RE, na=False)]
    if age < 18:
        candidates = candidates[candidates["Adulto"] != "1"]
    if age >= 2:
        candidates = candidates[candidates["Código"].str[0] != "P"]
        candidates = candidates[
            ~candidates["Descripción"].str.contains(
                r"recién nacido|neonatal", case=False, na=False, regex=True
            )
        ]
    return [candidates.sample(1).iloc[0]]


def _procedure_candidates(
    diags: list[pd.Series], sex: str, query_override: str | None = None
) -> pd.DataFrame:
    """Top-N procedimientos por similitud de embedding, con pre-filtros anatómicos."""
    embeddings = _get_procedure_embeddings()
    model      = _get_embedding_model()

    query    = query_override if query_override else " | ".join(d["Descripción"] for d in diags)
    diag_emb = model.encode([query], normalize_embeddings=True)[0]

    if sex == "Hombre":
        sex_mask = (PROC_DF["Mujer"] != "1").to_numpy()
    elif sex == "Mujer":
        sex_mask = (PROC_DF["Hombre"] != "1").to_numpy()
    else:
        sex_mask = np.ones(len(PROC_DF), dtype=bool)

    # Filtro por sistema orgánico
    systems = _get_proc_systems(diags[0]["Código"] if diags else "")
    if systems and not query_override:
        sys_mask   = PROC_DF["Código"].str[1].isin(systems).to_numpy()
        combined   = sex_mask & sys_mask
        valid_mask = combined if combined.sum() >= N_CANDIDATES else sex_mask
    else:
        valid_mask = sex_mask

    # Filtro de lateralidad: excluir procedimientos del lado contrario al diagnóstico
    if diags and not query_override:
        m_lat = _LAT_DESC_RE.search(diags[0]["Descripción"])
        if m_lat:
            lat_diag = _norm_laterality(m_lat.group(1))
            opposite_pat = _LAT_LEFT_RE if lat_diag == "Derecha" else (
                           _LAT_RIGHT_RE if lat_diag == "Izquierda" else None)
            if opposite_pat is not None:
                lat_mask = ~PROC_DF["Descripción"].str.contains(opposite_pat, na=False).to_numpy()
                with_lat = valid_mask & lat_mask
                if with_lat.sum() >= N_CANDIDATES:
                    valid_mask = with_lat

    # Filtro tronco: para lesiones de extremidad (S40-S99) excluir procedimientos de tronco
    if diags and not query_override and diags[0]["Código"][0] == 'S':
        sub = diags[0]["Código"][1:3]
        if '40' <= sub <= '99':
            trunk_mask = ~PROC_DF["Descripción"].str.contains(_TRUNK_DESC_RE, na=False).to_numpy()
            with_trunk = valid_mask & trunk_mask
            if with_trunk.sum() >= N_CANDIDATES:
                valid_mask = with_trunk

    valid_idx    = np.where(valid_mask)[0]
    sims         = embeddings[valid_idx] @ diag_emb
    top_n        = min(N_CANDIDATES, len(sims))
    top_local    = np.argpartition(sims, -top_n)[-top_n:]
    selected_idx = valid_idx[top_local]

    return PROC_DF.iloc[selected_idx].reset_index(drop=True)


def _generate_clinical_data(
    diags: list[pd.Series],
    candidates: pd.DataFrame,
    sex: str,
    age: int,
    *,
    candidate_comorbidities: str | None = None,
) -> dict:
    """Llama a OpenAI para seleccionar procedimiento y generar datos clínicos.

    candidate_comorbidities: lista RAE-CMBD preseleccionada; el LLM filtra las coherentes.
    Si es None, el LLM las genera libremente.
    """
    diag_text = "\n".join(f"- [{d['Código']}] {d['Descripción']}" for d in diags)
    options   = "\n".join(
        f"{i + 1}. [{row['Código']}] {row['Descripción']}"
        for i, row in candidates.iterrows()
    )

    system_msg = (
        "Eres un médico especialista completando fichas clínicas para una lista de espera quirúrgica española. "
        "Responde siempre en español con JSON válido. Todos los campos son obligatorios y deben contener "
        "información clínica real y coherente; nunca cadenas vacías."
    )

    if candidate_comorbidities is not None:
        comorbidities_instruction = (
            f"- `comorbilidades`: de la siguiente lista (prevalencias reales del SNS), "
            f"selecciona solo las clínicamente coherentes con el diagnóstico y la edad del paciente. "
            f"Descarta las que no encajen; si ninguna es coherente devuelve \"Ninguna\".\n"
            f"  Candidatas: {candidate_comorbidities}\n"
        )
    else:
        comorbidities_instruction = (
            "- `comorbilidades`: coherentes con la edad y el diagnóstico; Ninguna si el paciente es joven y sano.\n"
        )

    user_msg = (
        f"Paciente: {sex}, {age} años.\n\n"
        f"Diagnósticos (ICD-10-ES):\n{diag_text}\n\n"
        f"Procedimientos candidatos:\n{options}\n\n"
        "### Selección del procedimiento\n"
        "Elige el número del procedimiento que:\n"
        "- Trate directamente el diagnóstico principal (mismo sistema corporal y anatomía).\n"
        "- Sea terapéutico en lugar de diagnóstico cuando sea posible.\n"
        "- Si hay varios diagnósticos, prioriza el más grave.\n\n"
        "### Campos clínicos\n"
        f"- `tipo_cirugia`: uno de — {' | '.join(TIPO_CIRUGIA_OPTIONS)}\n"
        f"- `lateralidad`: {' | '.join(LATERALIDAD_OPTIONS)}\n"
        "- `otros_parametros`: usa el formato IMC: XX.X, ASA: Y, Alergias: Z. "
        "ASA I = joven sano; II = comorbilidad leve; III = comorbilidad moderada o >65 años; "
        "IV = riesgo vital. Alergias: Ninguna, penicilina, AINEs, látex, contraste yodado…\n"
        + comorbidities_instruction +
        "- `curso_clinico`: 2-3 frases sobre la evolución del caso en consultas previas.\n"
        "- `observaciones`: hallazgos o condicionantes clínicos relevantes para la cirugía, mínimo una frase.\n"
        "- `intervenciones_previas`: procedimientos quirúrgicos previos relacionados, o Ninguna.\n\n"
        f"Devuelve ÚNICAMENTE este objeto JSON (todos los campos obligatorios):\n"
        "{{\n"
        f'  "numero_procedimiento": <entero 1-{len(candidates)}>,\n'
        '  "anatomia_principal": "<parte anatómica concreta, p.ej. \'rodilla derecha\' o \'colon sigmoide\'; cadena vacía si no aplica>",\n'
        '  "procedimiento_correcto": <true si el procedimiento actúa sobre esa anatomía, false en caso contrario>,\n'
        '  "tipo_cirugia": "<valor del enum>",\n'
        '  "lateralidad": "<valor del enum>",\n'
        '  "observaciones": "<texto>",\n'
        '  "curso_clinico": "<texto>",\n'
        '  "intervenciones_previas": "<texto>",\n'
        '  "otros_parametros": "<IMC: XX.X, ASA: Y, Alergias: Z>",\n'
        '  "comorbilidades": "<texto>"\n'
        "}}"
    )

    try:
        resp = _get_openai_client().chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": user_msg},
            ],
            max_tokens=OPENAI_MAX_TOKENS,
            temperature=OPENAI_TEMPERATURE,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        num  = int(data.get("numero_procedimiento", 1)) - 1
        data["numero_procedimiento"] = max(0, min(num, len(candidates) - 1))
        for field in ("comorbilidades", "intervenciones_previas"):
            v = data.get(field)
            if isinstance(v, list):
                data[field] = ", ".join(str(x) for x in v)
        return data
    except Exception as e:
        print(f"\n[WARN] Error OpenAI: {e}", flush=True)
        return _CLINICAL_FALLBACK.copy()


def generate_patient() -> dict:
    birth_date, age, sex = _patient_data()
    diags      = _select_diagnoses(sex, age)
    candidates = _procedure_candidates(diags, sex)
    clinical   = _generate_clinical_data(diags, candidates, sex, age)

    if not clinical.get("procedimiento_correcto", True):
        anatomy = clinical.get("anatomia_principal", "").strip()
        if anatomy:
            candidates = _procedure_candidates(diags, sex, query_override=anatomy)
            clinical   = _generate_clinical_data(diags, candidates, sex, age)

    d1           = diags[0]
    proc_idx     = _fix_procedure_side(diags, candidates, clinical["numero_procedimiento"])
    proc         = candidates.iloc[proc_idx]
    service      = service_by_procedure(proc["Código"])
    surgery_type = _fix_surgery_type(proc["Código"], clinical.get("tipo_cirugia", ""))
    admission_date = date.today() - timedelta(days=random.randint(0, 90))

    priority = calculate_priority(age, surgery_type, admission_date.strftime("%Y-%m-%d"), None)

    return {
        "ID_Paciente":               str(uuid.uuid4()),
        "Nombre_Apellidos":          _full_name(sex),
        "Fecha_Nacimiento":          birth_date,
        "Medico_Peticionario":       _doctor(),
        "Edad":                      age,
        "Sexo":                      sex,
        "Prioridad":                 priority,
        "Codigo_Diagnostico":      d1["Código"],
        "Descripcion_Diagnostico": d1["Descripción"],
        "Codigo_Procedimiento":      proc["Código"],
        "Descripcion_Procedimiento": proc["Descripción"],
        "Tipo_Cirugia":              surgery_type,
        "Servicio":                  service,
        "Lateralidad":               _extract_laterality(proc["Descripción"], clinical.get("lateralidad", "No aplica")),
        "Observaciones":             clinical.get("observaciones", ""),
        "Curso_Clinico":             clinical.get("curso_clinico", ""),
        "Intervenciones_Previas":    clinical.get("intervenciones_previas", "Ninguna"),
        "Otros_Parametros_Clinicos": clinical.get("otros_parametros", ""),
        "Comorbilidades":            clinical.get("comorbilidades", "Ninguna"),
        "Fecha_Ingreso":             admission_date.strftime("%Y-%m-%d"),
        "Fecha_Intervencion":        None,
        "Quirofano":                 None,
        "Duracion_Horas":            None,
    }


def generate_dataset(n: int = 500) -> pd.DataFrame:
    rows = []
    for i in range(n):
        print(f"  Generando paciente {i + 1}/{n}...", end="\r")
        rows.append(generate_patient())
    print()
    return pd.DataFrame(rows)


PATIENT_COLUMNS = [
    "ID_Paciente",
    "Nombre_Apellidos",
    "Fecha_Nacimiento",
    "Medico_Peticionario",
]

WAITLIST_COLUMNS = [
    "ID_Paciente", "Edad", "Sexo", "Prioridad",
    "Codigo_Diagnostico", "Descripcion_Diagnostico",
    "Codigo_Procedimiento", "Descripcion_Procedimiento",
    "Tipo_Cirugia", "Servicio", "Lateralidad", "Observaciones", "Curso_Clinico",
    "Intervenciones_Previas", "Otros_Parametros_Clinicos", "Comorbilidades",
    "Fecha_Ingreso", "Fecha_Intervencion", "Quirofano", "Duracion_Horas",
]


if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    n    = int(args[0]) if args else 500

    print(f"Generando {n} pacientes con OpenAI ({OPENAI_MODEL})...")
    df = generate_dataset(n)

    CACHE_DIR.mkdir(exist_ok=True)
    patients_path = CACHE_DIR / "pacientes2.csv"
    waitlist_path = CACHE_DIR / "lista_espera_quirurgica2.csv"

    df[PATIENT_COLUMNS].to_csv(patients_path, index=False, encoding="utf-8-sig")
    df[WAITLIST_COLUMNS].to_csv(waitlist_path, index=False, encoding="utf-8-sig")

    print(f"  -> {patients_path}")
    print(f"  -> {waitlist_path}")
    print(f"\n=== Estadísticas ===")
    print(f"  Total: {len(df)}  |  Edad media: {df['Edad'].mean():.1f}  |  "
          f"H/M: {(df['Sexo']=='Hombre').sum()}/{(df['Sexo']=='Mujer').sum()}")
    for _, row in df.head(3).iterrows():
        print(f"  [{row['Codigo_Diagnostico']}] {row['Descripcion_Diagnostico'][:50]}")
        print(f"    → [{row['Codigo_Procedimiento']}] {row['Descripcion_Procedimiento'][:50]}")
