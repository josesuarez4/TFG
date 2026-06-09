"""Registro persistente de la última planificación ejecutada por servicio."""

import json
from datetime import date, timedelta
from pathlib import Path

_LOG_PATH = Path(__file__).parent.parent / "datos_generados" / "planning_log.json"


def save_planning(service: str, end_date: date) -> None:
    log = _load_raw()
    log[service] = end_date.isoformat()
    _LOG_PATH.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def get_reference_date(service: str) -> date:
    """Devuelve el día siguiente al fin de la última planificación del servicio,
    u hoy si el servicio nunca ha sido planificado."""
    log = _load_raw()
    if service not in log:
        return date.today()
    end = date.fromisoformat(log[service])
    next_day = end + timedelta(days=1)
    return max(next_day, date.today())


def _load_raw() -> dict:
    if not _LOG_PATH.exists():
        return {}
    try:
        return json.loads(_LOG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
