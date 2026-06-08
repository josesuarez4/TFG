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
    """Curva en U: 100 % en neonatos, mínimo en adolescentes, sube con la vejez."""
    young_pct = max(0.0, 100.0 * (1.0 - age / _PEDIATRIC_THRESHOLD))
    old_pct   = min(age / 90.0 * 100.0, 100.0)
    return max(young_pct, old_pct)


def calculate_priority(
    age: int,
    surgery_type: str,
    admission_date: str,
    intervention_date: "str | None" = None,  # no se usa; se conserva por compatibilidad
) -> float:
    """Score 0–100: espera (40 %) + edad curva-U (30 %) + invasividad (30 %)."""
    d_start = date.fromisoformat(admission_date)
    # Usar siempre hoy: la espera refleja el tiempo real transcurrido desde el ingreso,
    # independientemente de si el paciente tiene cita asignada o no.
    days    = max(0, (date.today() - d_start).days)

    wait_pct = min(days / 365.0 * 100.0, 100.0)
    surg_pct = _SURGERY_TYPE_PCT.get(surgery_type, 0.0)

    return round(wait_pct * 0.40 + _age_pct(age) * 0.30 + surg_pct * 0.30, 1)
