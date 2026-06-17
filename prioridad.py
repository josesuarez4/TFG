"""Cálculo del score de prioridad quirúrgica (0.0 – 100.0)."""

from datetime import date

_SURGERY_TYPE_PCT: dict[str, float] = {
    "Abierta":               100.0,
    "Robótica":               66.7,
    "Laparoscópica":          66.7,
    "Artroscópica":           33.3,
    "Endoscópica":            33.3,
    "Mínimamente invasiva":   33.3,
    "Percutánea":              0.0,
    "No aplica":               0.0,
}

# Curva en V asimétrica: mínimo en _AGE_VERTEX con suelo _AGE_MIN,
# decrece desde 100 en neonatos y crece hasta 100 a los 90 años.
_AGE_VERTEX: float = 35.0
_AGE_MIN:    float = 15.0


def _age_pct(age: int) -> float:
    """Curva en V con vértice en ~35 años: prioriza neonatos y pacientes de edad avanzada."""
    if age <= _AGE_VERTEX:
        t = (_AGE_VERTEX - age) / _AGE_VERTEX
    else:
        t = (age - _AGE_VERTEX) / (90.0 - _AGE_VERTEX)
    return _AGE_MIN + (100.0 - _AGE_MIN) * t


def calculate_priority(
    age: int,
    surgery_type: str,
    admission_date: str,
    intervention_date: "str | None" = None,
    reference_date: "date | None" = None,
) -> float:
    """Score 0–100: espera (40 %) + edad (35 %) + invasividad (25 %).

    reference_date: fecha hasta la que se calcula la espera. Si no se indica se
    usa el día de hoy. Para pacientes sin cita en servicios ya planificados se utiliza 
    la fecha de la última planificación como referencia, lo que evita que su prioridad 
    se dispare al día siguiente de la planificación.
    """
    d_start = date.fromisoformat(admission_date)
    d_ref   = (
        date.fromisoformat(intervention_date[:10]) if intervention_date is not None
        else reference_date if reference_date is not None
        else date.today()
    )
    days    = max(0, (d_ref - d_start).days)

    wait_pct = min(days / 365.0 * 100.0, 100.0)
    surg_pct = _SURGERY_TYPE_PCT.get(surgery_type, 0.0)

    return round(wait_pct * 0.40 + _age_pct(age) * 0.35 + surg_pct * 0.25, 1)
