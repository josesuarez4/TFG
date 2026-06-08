"""Asignación de slots quirúrgicos por prioridad para un servicio y ventana temporal."""

from datetime import date, datetime, timedelta

import pandas as pd

from prioridad import calculate_priority
from quirofanos import ROOMS_BY_SERVICE
from especialistas import SPECIALISTS_BY_ROOM

_OR_TIME_SLOTS = [
    datetime(2000, 1, 1, h, m)
    for h in range(8, 22)
    for m in (0, 30)
    if not (h == 21 and m == 30)  # 21:30 + cirugía mínima (0.5h) + limpieza (0.5h) = 22:30 > cierre
]

_TURNOVER_MINUTES: int = 30


def _specialist_available(
    room: str,
    slot_start: datetime,
    slot_end: datetime,
    unavailable_specs: dict[str, list[tuple[datetime, datetime]]],
) -> bool:
    """Comprueba que al menos un especialista del quirófano cubre el turno y está libre."""
    specs = SPECIALISTS_BY_ROOM.get(room, [])
    if not specs:
        return True
    for spec in specs:
        if slot_start.weekday() not in spec["days"]:
            continue
        # Verificar que el slot empieza y termina dentro del turno del especialista
        shift_start = datetime(slot_start.year, slot_start.month, slot_start.day, spec["start_hour"], 0)
        shift_end   = datetime(slot_start.year, slot_start.month, slot_start.day, spec["end_hour"],    0)
        if not (slot_start >= shift_start and slot_end <= shift_end):
            continue
        # Verificar que no coincide con ningún período de no disponibilidad
        conflicts = unavailable_specs.get(spec["id"], [])
        if not any(slot_start < u_end and slot_end > u_start for u_start, u_end in conflicts):
            return True
    return False


def _assign_slot(
    service: str,
    earliest: date,
    max_date: date,
    duration: float,
    used_slots: dict[str, list[tuple[datetime, datetime]]],
    unavailable_specs: dict[str, list[tuple[datetime, datetime]]] | None = None,
    rooms_override: list[str] | None = None,
) -> tuple[str, str] | tuple[None, None]:
    """Primer slot libre en días laborables entre earliest y max_date."""
    rooms = rooms_override if rooms_override is not None else ROOMS_BY_SERVICE.get(service, [])
    if not rooms:
        return None, None

    _unavail = unavailable_specs or {}
    td_duration = timedelta(hours=duration)
    td_turnover = timedelta(minutes=_TURNOVER_MINUTES)
    day = earliest
    while day <= max_date:
        if day.weekday() < 5:
            for slot_time in _OR_TIME_SLOTS:
                start    = datetime(day.year, day.month, day.day, slot_time.hour, slot_time.minute)
                end      = start + td_duration
                end_blok = end + td_turnover
                for room in rooms:
                    if not any(start < e and end_blok > s for s, e in used_slots.get(room, [])):
                        if _specialist_available(room, start, end_blok, _unavail):
                            used_slots.setdefault(room, []).append((start, end_blok))
                            return room, start.strftime("%Y-%m-%d %H:%M")
        day += timedelta(days=1)
    return None, None


def service_planning(
    df: pd.DataFrame,
    service: str,
    end_date: date,
    start_date: date | None = None,
    closed_days: dict[str, list[date]] | None = None,
    unavailable_specs: dict[str, list[tuple[datetime, datetime]]] | None = None,
    tarde_room: str | None = None,
) -> tuple[pd.DataFrame, int]:
    """Planifica pacientes de un servicio dentro de una ventana de fechas.

    1. Reconstruye used_slots con todos los slots existentes (cualquier servicio).
    2. Bloquea los días cerrados indicados en closed_days {quirofano: [fecha, ...]}.
    3. Bloquea especialistas no disponibles {spec_id: [fecha, ...]}.
    4. Recalcula prioridad en tiempo real (espera = hoy − ingreso).
    5. Asigna por prioridad descendente dentro de la ventana solo a pacientes sin cita.

    Los slots ya asignados dentro de la ventana se respetan y no se modifican.
    Devuelve (df_actualizado, n_pacientes_asignados).
    """
    today      = date.today()
    start_date = start_date or today
    df       = df.copy()
    # Cuando todas las celdas son NaN pandas infiere float64; forzar object para poder asignar cadenas
    df["Fecha_Intervencion"] = df["Fecha_Intervencion"].astype(object)
    df["Quirofano"]          = df["Quirofano"].astype(object)

    service_mask = df["Servicio"] == service

    # Añadir quirófano de tarde al listado del servicio si está asignado
    _rooms_override = ROOMS_BY_SERVICE.get(service, []) + ([tarde_room] if tarde_room else [])

    # Reconstruir used_slots con todos los slots existentes (todos los servicios)
    used_slots: dict[str, list[tuple[datetime, datetime]]] = {}
    for _, row in df[df["Fecha_Intervencion"].notna()].iterrows():
        room  = str(row["Quirofano"])
        start = pd.to_datetime(row["Fecha_Intervencion"]).to_pydatetime()
        dur   = float(row.get("Duracion_Horas") or 1.0)
        end   = start + timedelta(hours=dur) + timedelta(minutes=_TURNOVER_MINUTES)
        used_slots.setdefault(room, []).append((start, end))

    # Bloquear días cerrados: ocupa todo el día para que _assign_slot los salte
    if closed_days:
        for room, days in closed_days.items():
            for day in days:
                block_start = datetime(day.year, day.month, day.day, 0, 0)
                block_end   = datetime(day.year, day.month, day.day, 23, 59)
                used_slots.setdefault(room, []).append((block_start, block_end))

    # Recalcular prioridad en tiempo real para los pacientes del servicio
    for idx in df[service_mask].index:
        row = df.loc[idx]
        df.loc[idx, "Prioridad"] = calculate_priority(
            int(row["Edad"]),
            str(row["Tipo_Cirugia"]),
            str(row["Fecha_Ingreso"]),
            None,
        )

    # Ordenar sin slot por prioridad descendente y asignar
    to_schedule = (
        df[service_mask & df["Fecha_Intervencion"].isna()]
        .sort_values("Prioridad", ascending=False)
    )

    n_assigned = 0
    for idx, row in to_schedule.iterrows():
        admission = date.fromisoformat(str(row["Fecha_Ingreso"]))
        earliest  = max(admission + timedelta(days=14), start_date)
        if earliest > end_date:
            continue

        duration = float(row.get("Duracion_Horas") or 1.0)
        room, slot = _assign_slot(service, earliest, end_date, duration, used_slots, unavailable_specs, _rooms_override)
        if room:
            df.loc[idx, "Fecha_Intervencion"] = slot
            df.loc[idx, "Quirofano"]          = room
            df.loc[idx, "Prioridad"]          = calculate_priority(
                int(row["Edad"]),
                str(row["Tipo_Cirugia"]),
                str(row["Fecha_Ingreso"]),
                slot,
            )
            n_assigned += 1

    return df, n_assigned
