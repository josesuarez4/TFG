"""Gestión de los dos quirófanos de turno de tarde compartidos entre servicios."""

import json
from pathlib import Path

# Los dos quirófanos de tarde disponibles para todo el hospital
TARDE_ROOMS = ["TARDE-Q1", "TARDE-Q2"]

_ASSIGNMENT_PATH = Path(__file__).parent.parent / "datos_generados" / "quirofanos_tarde.json"


def load_tarde_assignment() -> dict[str, str]:
    """Devuelve {servicio: quirofano} para los servicios con quirófano de tarde asignado."""
    if _ASSIGNMENT_PATH.exists():
        return json.loads(_ASSIGNMENT_PATH.read_text(encoding="utf-8"))
    return {}


def save_tarde_assignment(assignment: dict[str, str]) -> None:
    """Persiste la asignación {servicio: quirofano}."""
    _ASSIGNMENT_PATH.parent.mkdir(exist_ok=True)
    _ASSIGNMENT_PATH.write_text(
        json.dumps(assignment, ensure_ascii=False, indent=2), encoding="utf-8"
    )
