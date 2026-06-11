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

# Edad a la que el componente pediátrico llega a 0 (curva en U)
_PEDIATRIC_THRESHOLD: float = 14.0


def _age_pct(age: int) -> float:
    """Curva en U: 100 % en neonatos, mínimo en adolescentes, sube con los años."""
    young_pct = max(0.0, 100.0 * (1.0 - age / _PEDIATRIC_THRESHOLD))
    old_pct   = min(age / 90.0 * 100.0, 100.0)
    return max(young_pct, old_pct)


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
