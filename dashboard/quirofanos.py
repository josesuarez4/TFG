"""Configuración de quirófanos del hospital: asignación por servicio y quirófanos de tarde."""

import json
from pathlib import Path

# ── Quirófanos de turno de tarde ───────────────────────────────────────────────

PM_ROOMS = ["TARDE-Q1", "TARDE-Q2"]

_ASSIGNMENT_PATH = Path(__file__).parent.parent / "datos_generados" / "dashboard" / "quirofanos_tarde.json"


def load_pm_assignment() -> dict[str, str]:
    """Devuelve {servicio: quirofano} para los servicios con quirófano de tarde asignado."""
    if _ASSIGNMENT_PATH.exists():
        return json.loads(_ASSIGNMENT_PATH.read_text(encoding="utf-8"))
    return {}


def save_pm_assignment(assignment: dict[str, str]) -> None:
    """Persiste la asignación {servicio: quirofano}."""
    _ASSIGNMENT_PATH.parent.mkdir(exist_ok=True)
    _ASSIGNMENT_PATH.write_text(
        json.dumps(assignment, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── Quirófanos por servicio ────────────────────────────────────────────────────

ROOMS_BY_SERVICE: dict[str, list[str]] = {
    "Traumatología y Cirugía Ortopédica":   ["TRAU-Q1", "TRAU-Q2", "TRAU-Q3", "TRAU-Q4"],
    "Cirugía General y Aparato Digestivo":  ["CGAD-Q1", "CGAD-Q2", "CGAD-Q3"],
    "Urología":                             ["UROL-Q1", "UROL-Q2"],
    "Neurocirugía":                         ["NEUR-Q1", "NEUR-Q2"],
    "Cirugía Cardiovascular":               ["CCAR-Q1", "CCAR-Q2"],
    "Angiología y Cirugía Vascular":        ["ANGI-Q1"],
    "Oftalmología":                         ["OFTA-Q1", "OFTA-Q2"],
    "Otorrinolaringología":                 ["OTOR-Q1"],
    "Cirugía Torácica":                     ["CTOR-Q1"],
    "Cirugía Maxilofacial":                 ["CMXF-Q1"],
    "Dermatología":                         ["DERM-Q1"],
    "Cirugía Plástica":                     ["CPLA-Q1"],
    "Ginecología y Obstetricia":            ["GINE-Q1", "GINE-Q2"],
    "Cirugía Pediátrica":                   ["CPED-Q1"],
}
