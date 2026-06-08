"""Gestión de gaps quirúrgicos disponibles tras cancelaciones."""

import uuid
from pathlib import Path

import pandas as pd

GAPS_PATH = Path(__file__).parent.parent / "datos_generados" / "gaps_disponibles.csv"

_COLUMNS = [
    "id_gap", "fecha_intervencion", "quirofano", "servicio",
    "duracion_horas", "codigo_procedimiento", "id_paciente_cancelado",
    "motivo_cancelacion",
]

# Pesos por posición en el código ICD-10-PCS (sección, sistema, operación, parte, abordaje, dispositivo, calificador)
_PROC_WEIGHTS = [0.20, 0.20, 0.25, 0.15, 0.10, 0.05, 0.05]


def procedure_similarity(code1: str, code2: str) -> float:
    """Similitud 0–1 entre dos códigos ICD-10-PCS por coincidencia de caracteres ponderada."""
    score = 0.0
    for i, (c1, c2) in enumerate(zip(str(code1)[:7].upper(), str(code2)[:7].upper())):
        if c1 == c2:
            score += _PROC_WEIGHTS[i]
    return round(score, 4)


def find_candidates(df: pd.DataFrame, gap: dict, n: int = 3, offset: int = 0) -> pd.DataFrame:
    """Devuelve hasta n+1 candidatos a partir de la posición offset.

    Criterios de elegibilidad:
      - Mismo servicio que el gap.
      - Sin cita asignada.
      - Duración de la cirugía ≤ duración del gap.
      - No es el paciente que canceló originalmente.

    Puntuación final: 60 % prioridad + 40 % similitud de procedimiento.
    Devuelve n+1 filas si existen más tras la página actual; n o menos si no hay más.
    """
    mask = (
        (df["Servicio"] == gap["servicio"])
        & df["Fecha_Intervencion"].isna()
        & (df["Duracion_Horas"].fillna(0) <= float(gap["duracion_horas"]))
        & (df["ID_Paciente"] != gap.get("id_paciente_cancelado", ""))
    )
    candidates = df[mask].copy()
    if candidates.empty:
        return candidates

    candidates["Similitud"] = candidates["Codigo_Procedimiento"].apply(
        lambda c: procedure_similarity(str(c), str(gap["codigo_procedimiento"]))
    )
    candidates["Puntuacion"] = (
        0.6 * (candidates["Prioridad"] / 100) + 0.4 * candidates["Similitud"]
    ).round(4)
    return (
        candidates.sort_values("Puntuacion", ascending=False)
        .iloc[offset: offset + n + 1]
        .reset_index(drop=True)
    )


def save_gap(
    fecha_intervencion: str,
    quirofano: str,
    servicio: str,
    duracion_horas: float,
    codigo_procedimiento: str,
    id_paciente_cancelado: str,
    motivo_cancelacion: str = "",
) -> None:
    """Persiste un gap disponible en el CSV."""
    row = {
        "id_gap":                 str(uuid.uuid4()),
        "fecha_intervencion":     fecha_intervencion,
        "quirofano":              quirofano,
        "servicio":               servicio,
        "duracion_horas":         duracion_horas,
        "codigo_procedimiento":   codigo_procedimiento,
        "id_paciente_cancelado":  id_paciente_cancelado,
        "motivo_cancelacion":     motivo_cancelacion,
    }
    df = load_gaps()
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    df.to_csv(GAPS_PATH, index=False, encoding="utf-8-sig")


def load_gaps() -> pd.DataFrame:
    if GAPS_PATH.exists():
        return pd.read_csv(GAPS_PATH)
    return pd.DataFrame(columns=_COLUMNS)


def remove_gap(gap_id: str) -> None:
    df = load_gaps()
    df[df["id_gap"] != gap_id].to_csv(GAPS_PATH, index=False, encoding="utf-8-sig")
