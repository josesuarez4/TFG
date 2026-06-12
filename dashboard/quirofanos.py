"""Configuración de quirófanos del hospital: asignación por servicio y quirófanos de tarde."""

import json
from datetime import date
from pathlib import Path

# ── Quirófanos de turno de tarde ───────────────────────────────────────────────

PM_ROOMS = ["TARDE-Q1", "TARDE-Q2"]

_ASSIGNMENT_PATH = Path(__file__).parent.parent / "datos_generados" / "dashboard" / "quirofanos_tarde.json"


def load_pm_assignments() -> list[dict]:
    """Devuelve todas las asignaciones de quirófanos de tarde como lista de registros."""
    if _ASSIGNMENT_PATH.exists():
        data = json.loads(_ASSIGNMENT_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    return []


def load_pm_assignment(for_date: date | None = None) -> dict[str, str]:
    """Devuelve {quirofano: servicio} para las asignaciones activas en for_date (por defecto hoy)."""
    target = for_date or date.today()
    result = {}
    for a in load_pm_assignments():
        try:
            start = date.fromisoformat(a["fecha_inicio"])
            end   = date.fromisoformat(a["fecha_fin"])
            if start <= target <= end:
                result[a["quirofano"]] = a["servicio"]
        except (KeyError, ValueError):
            continue
    return result


def save_pm_assignments(assignments: list[dict]) -> None:
    """Persiste la lista completa de asignaciones."""
    _ASSIGNMENT_PATH.parent.mkdir(exist_ok=True)
    _ASSIGNMENT_PATH.write_text(
        json.dumps(assignments, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def has_pm_overlap(
    assignments: list[dict],
    quirofano: str,
    fecha_inicio: date,
    fecha_fin: date,
    exclude_idx: int | None = None,
) -> bool:
    """Devuelve True si el rango se solapa con alguna asignación existente del mismo quirófano."""
    for i, a in enumerate(assignments):
        if i == exclude_idx or a.get("quirofano") != quirofano:
            continue
        try:
            a_start = date.fromisoformat(a["fecha_inicio"])
            a_end   = date.fromisoformat(a["fecha_fin"])
            if fecha_inicio <= a_end and fecha_fin >= a_start:
                return True
        except (KeyError, ValueError):
            continue
    return False


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
