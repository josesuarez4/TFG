import random
import re
from datetime import date

import pandas as pd

_MALE_ONLY_RE   = re.compile(r"\bmasculin[ao]?\b", re.IGNORECASE)
_FEMALE_ONLY_RE = re.compile(
    r"\bfemenin[ao]?\b|\bmatern[ao]?\b|\bembaraz"
    r"|\bovario\b|\bvagina\b|\bvulva\b|\b[uú]terin[ao]?\b"
    r"|\bfalopio\b|\bendometri|\bplacenta\b",
    re.IGNORECASE,
)

# Diagnósticos quirúrgicos más frecuentes por edad y sexo (Tabla 16 RAE-CMBD 2022)
# Formato: ((icd_inicio, icd_fin), n_altas_SNS_2022)
_DIAG_FREQ: dict[tuple[str, str], list[tuple[tuple[str, str], int]]] = {
    ("<1", "Hombre"): [
        (("Q80", "Q89"), 496),
        (("K40", "K46"), 424),
        (("Q20", "Q28"), 392),
        (("Q38", "Q45"), 349),
        (("Q60", "Q64"), 176),
    ],
    ("<1", "Mujer"): [
        (("Q20", "Q28"), 324),
        (("Q80", "Q89"), 324),
        (("Q38", "Q45"), 153),
        (("K40", "K46"), 105),
        (("P05", "P07"),  84),
    ],
    ("1-14", "Hombre"): [
        (("K35", "K38"), 5826),
        (("J35", "J36"), 3727),
        (("S40", "S59"), 2969),
        (("Q60", "Q64"), 2362),
        (("Q80", "Q89"), 1600),
    ],
    ("1-14", "Mujer"): [
        (("K35", "K38"), 3314),
        (("J35", "J36"), 2483),
        (("S40", "S59"), 1355),
        (("Q80", "Q89"), 1280),
        (("Q20", "Q28"),  572),
    ],
    ("15-44", "Hombre"): [
        (("K35", "K38"), 10738),
        (("S40", "S59"),  7457),
        (("S70", "S89"),  7008),
        (("M23", "M25"),  5507),
        (("J34", "J39"),  3106),
    ],
    ("15-44", "Mujer"): [
        (("O40", "O41"), 12723),
        (("O20", "O29"),  9763),
        (("O48", "O48"),  9162),
        (("O60", "O75"),  8255),
        (("K35", "K38"),  7990),
    ],
    ("45-64", "Hombre"): [
        (("K40", "K46"), 13638),
        (("I21", "I22"), 12461),
        (("M15", "M19"), 10835),
        (("K80", "K87"),  7863),
        (("S40", "S59"),  6248),
    ],
    ("45-64", "Mujer"): [
        (("C50", "C50"), 11833),
        (("K80", "K87"), 10948),
        (("M15", "M19"),  8687),
        (("S70", "S89"),  7428),
        (("D25", "D28"),  7247),
    ],
    ("65-74", "Hombre"): [
        (("M15", "M19"),  9437),
        (("C67", "C67"),  9024),
        (("K40", "K46"),  8870),
        (("N40", "N40"),  6934),
        (("I21", "I22"),  6513),
    ],
    ("65-74", "Mujer"): [
        (("M15", "M19"), 14174),
        (("K80", "K87"),  5581),
        (("S40", "S59"),  5318),
        (("C50", "C50"),  4680),
        (("K40", "K46"),  4209),
    ],
    ("75+", "Hombre"): [
        (("C67",   "C67"),   11342),
        (("S72.0", "S72.0"), 10037),
        (("K40",   "K46"),    9363),
        (("M15",   "M19"),    7148),
        (("I44",   "I49"),    6307),
    ],
    ("75+", "Mujer"): [
        (("S72.0", "S72.0"), 29928),
        (("M15",   "M19"),   13542),
        (("K80",   "K87"),    6084),
        (("T82",   "T85"),    5702),
        (("M84",   "M84"),    5449),
    ],
}

# Los diagnósticos del top-5 representan ~45 % de las altas; el resto va a "otros"
_FRACTION_OTHERS = 0.55

# Comorbilidades más frecuentes (Gráfico 18 RAE-CMBD 2022)
# Formato: (descripción, prevalencia_base, edad_mínima, male_mult)
# male_mult: >1 = más frecuente en hombres; ajuste preserva prevalencia media 50/50
_COMORBIDITIES: list[tuple[str, float, int | None, float]] = [
    ("Hipertensión arterial esencial",                   0.275, None,  1.1),
    ("Dislipemia",                                       0.269, None,  1.1),
    ("Obesidad / sobrepeso",                             0.102, None,  0.9),
    ("Otros trastornos nutricionales y metabólicos",     0.165, None,  1.0),
    ("Cardiopatía isquémica / aterosclerosis coronaria", 0.147,   45,  1.8),
    ("Diabetes mellitus tipo 2",                         0.145,   30,  1.2),
    ("Disritmias cardíacas",                             0.144,   45,  1.3),
    ("Trastorno por uso de sustancias psicotrópicas",    0.134, None,  1.5),
    ("Insuficiencia renal crónica",                      0.118,   40,  1.2),
    ("Hipertensión arterial con complicaciones",         0.117,   50,  1.2),
    ("Reacciones alérgicas",                             0.111, None,  0.9),
    ("Anemia",                                           0.108, None,  0.7),
    ("Insuficiencia respiratoria",                       0.116,   50,  1.1),
    ("Infección bacteriana inespecífica",                0.121, None,  1.0),
    ("Demencia y deterioro cognitivo",                   0.105,   65,  0.85),
]


def _age_multiplier(age: int) -> float:
    """Factor multiplicador de prevalencia de comorbilidades según tramo de edad, 
    creciente a partir de los 40 años."""
    if age < 40:  return 0.08
    if age < 55:  return 0.45
    if age < 65:  return 0.75
    if age < 75:  return 1.00
    return 1.30


def _age_group(age: int) -> str:
    """Clasifica una edad en uno de los tramos epidemiológicos usados por las tablas RAE-CMBD 2022."""
    if age < 1:   return "<1"
    if age <= 14: return "1-14"
    if age <= 44: return "15-44"
    if age <= 64: return "45-64"
    if age <= 74: return "65-74"
    return "75+"


def _in_range(code: str, start: str, end: str) -> bool:
    """Comprueba si un código CIE-10-ES está dentro del rango [start, end] 
    comparando solo los primeros caracteres del rango."""
    n = len(start)
    return start <= code[:n] <= end


def _filter_diag(rng: tuple[str, str], diag_df: pd.DataFrame, sex: str) -> pd.DataFrame:
    """Filtra el catálogo de diagnósticos a un rango de códigos, 
    aplicando además las exclusiones por sexo correspondientes."""
    start, end = rng
    mask   = diag_df["Código"].apply(lambda c: _in_range(c, start, end))
    subset = diag_df[mask].copy()
    if sex == "Hombre":
        subset = subset[subset["Mujer"] != "1"]
        subset = subset[~subset["Descripción"].str.contains(_FEMALE_ONLY_RE, na=False)]
    else:
        subset = subset[subset["Hombre"] != "1"]
        subset = subset[~subset["Descripción"].str.contains(_MALE_ONLY_RE, na=False)]
    return subset


def select_diagnosis_rae(sex: str, age: int, diag_df: pd.DataFrame) -> list[pd.Series]:
    """Diagnóstico principal con distribución RAE-CMBD 2022 estratificada por edad y sexo."""
    group      = _age_group(age)
    diag_freq  = _DIAG_FREQ.get((group, sex), [])
    primary: pd.Series | None = None

    if diag_freq:
        explicit_weights = [w for _, w in diag_freq]
        explicit_sum     = sum(explicit_weights)
        other_weight     = explicit_sum * _FRACTION_OTHERS / (1 - _FRACTION_OTHERS)
        all_ranges       = [rng for rng, _ in diag_freq]
        range_options    = [rng for rng, _ in diag_freq] + [None]
        total_weights    = explicit_weights + [other_weight]

        for _ in range(6):
            idx            = random.choices(range(len(range_options)), weights=total_weights)[0]
            selected_range = range_options[idx]

            if selected_range is None:
                candidates = diag_df.copy()
                if sex == "Hombre":
                    candidates = candidates[candidates["Mujer"] != "1"]
                    candidates = candidates[~candidates["Código"].str.startswith("O")]
                    candidates = candidates[~candidates["Descripción"].str.contains(_FEMALE_ONLY_RE, na=False)]
                else:
                    candidates = candidates[candidates["Hombre"] != "1"]
                    if not (20 <= age <= 60):
                        candidates = candidates[~candidates["Código"].str.startswith("O")]
                    candidates = candidates[~candidates["Descripción"].str.contains(_MALE_ONLY_RE, na=False)]
                if age >= 2:
                    candidates = candidates[candidates["Código"].str[0] != "P"]
                    candidates = candidates[
                        ~candidates["Descripción"].str.contains(
                            r"recién nacido|neonatal", case=False, na=False, regex=True
                        )
                    ]
                candidates = candidates[~candidates["Código"].apply(
                    lambda c: any(_in_range(c, s, e) for s, e in all_ranges)
                )]
                if not candidates.empty:
                    primary = candidates.sample(1).iloc[0]
                    break
            else:
                start_code, _ = selected_range
                if start_code.startswith("O") and (sex == "Hombre" or not (20 <= age <= 60)):
                    continue
                subset = _filter_diag(selected_range, diag_df, sex)
                if not subset.empty:
                    primary = subset.sample(1).iloc[0]
                    break

    if primary is None:
        candidates = diag_df.copy()
        if sex == "Hombre":
            candidates = candidates[candidates["Mujer"] != "1"]
            candidates = candidates[~candidates["Código"].str.startswith("O")]
            candidates = candidates[~candidates["Descripción"].str.contains(_FEMALE_ONLY_RE, na=False)]
        else:
            candidates = candidates[candidates["Hombre"] != "1"]
            candidates = candidates[~candidates["Descripción"].str.contains(_MALE_ONLY_RE, na=False)]
        if age >= 2:
            candidates = candidates[candidates["Código"].str[0] != "P"]
        primary = (candidates if not candidates.empty else diag_df).sample(1).iloc[0]

    return [primary]


def sample_comorbidities_rae(sex: str, age: int) -> str:
    """Comorbilidades por Bernoulli con prevalencias RAE-CMBD ajustadas por edad y sexo."""
    age_mult = _age_multiplier(age)
    selected: list[str] = []

    for name, base_prev, age_min, male_mult in _COMORBIDITIES:
        if age_min is not None and age < age_min:
            continue
        avg_mult   = 0.5 * male_mult + 0.5
        sex_factor = male_mult / avg_mult if sex == "Hombre" else 1.0 / avg_mult
        if random.random() < min(base_prev * age_mult * sex_factor, 0.90):
            selected.append(name)

    if len(selected) > 4:
        selected = random.sample(selected, 4)

    return ", ".join(selected) if selected else "Ninguna"


# Distribución de edad para altas quirúrgicas (Tabla 4 RAE-CMBD 2022)
_AGE_RANGES: list[tuple[int, int, float]] = [
    ( 0,   0, 0.027),
    ( 1,  14, 0.044),
    (15,  44, 0.194),
    (45,  64, 0.232),
    (65,  74, 0.169),
    (75,  90, 0.334),
]


def sample_age_rae(fake_instance) -> tuple[str, int, str]:
    """Genera (fecha_nacimiento, edad, sexo) con distribución RAE-CMBD 2022."""
    sex = random.choices(["Hombre", "Mujer"], weights=[0.497, 0.503])[0]

    min_age, max_age, _ = random.choices(
        _AGE_RANGES, weights=[w for *_, w in _AGE_RANGES]
    )[0]

    birth_date = fake_instance.date_of_birth(minimum_age=min_age, maximum_age=max_age)
    today = date.today()
    age   = today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )

    return birth_date.isoformat(), age, sex
