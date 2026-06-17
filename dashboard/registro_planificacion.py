import json
from datetime import date, timedelta
from pathlib import Path

_LOG_PATH = Path(__file__).parent.parent / "datos_generados" / "dashboard" / "registro_planificacion.json"


def save_planning(service: str, end_date: date) -> None:
    log_data = _load_raw()
    log_data[service] = end_date.isoformat()
    _LOG_PATH.write_text(json.dumps(log_data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_reference_date(service: str) -> date:
    """Devuelve el día siguiente al fin de la última planificación del servicio,
    u hoy si el servicio nunca ha sido planificado."""
    log_data = _load_raw()
    if service not in log_data:
        return date.today()
    last_end_date  = date.fromisoformat(log_data[service])
    day_after_last = last_end_date + timedelta(days=1)
    return max(day_after_last, date.today())


def _load_raw() -> dict:
    if not _LOG_PATH.exists():
        return {}
    try:
        return json.loads(_LOG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
