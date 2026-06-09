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
    pm_room: str | None = None,
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

    # Poner PM primero: sus slots (15:00+) se asignan antes que los de mañana para ese turno
    _rooms_override = ([pm_room] if pm_room else []) + ROOMS_BY_SERVICE.get(service, [])

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


def find_free_slots(
    rooms: list[str],
    from_date: date,
    duration: float,
    df_current: pd.DataFrame,
    n: int = 3,
    closed_days: dict[str, list[date]] | None = None,
    unavailable_specs: dict[str, list[tuple[datetime, datetime]]] | None = None,
) -> list[tuple[datetime, str]]:
    """Devuelve los n slots libres más próximos a from_date entre todos los quirófanos dados,
    respetando días cerrados y franjas de especialistas no disponibles."""
    closed_days       = closed_days or {}
    unavailable_specs = unavailable_specs or {}

    # Precomputar slots ocupados por quirófano
    occupied_by_room: dict[str, list[tuple[datetime, datetime]]] = {}
    for room in rooms:
        room_rows = df_current[df_current["Quirofano"] == room].copy()
        room_rows["_s"] = pd.to_datetime(room_rows["Fecha_Intervencion"], errors="coerce")
        room_rows["_e"] = room_rows["_s"] + pd.to_timedelta(
            room_rows["Duracion_Horas"].fillna(1), unit="h"
        ) + timedelta(minutes=_TURNOVER_MINUTES)
        occupied_by_room[room] = [
            (r["_s"].to_pydatetime(), r["_e"].to_pydatetime())
            for _, r in room_rows[room_rows["_s"].notna()].iterrows()
        ]

    slots: list[tuple[datetime, str]] = []
    day = from_date
    for _ in range(365):
        if len(slots) == n:
            break
        day_candidates: list[tuple[datetime, str]] = []
        for room in rooms:
            # Saltar si el quirófano está cerrado ese día
            if day in closed_days.get(room, []):
                continue
            specs = SPECIALISTS_BY_ROOM.get(room, [])
            if not specs:
                continue
            spec = specs[0]
            if day.weekday() not in set(spec["days"]):
                continue

            spec_id      = spec.get("id", "")
            spec_unavail = unavailable_specs.get(spec_id, [])
            t       = datetime(day.year, day.month, day.day, spec["start_hour"], 0)
            day_end = datetime(day.year, day.month, day.day, spec["end_hour"],    0)
            occupied = occupied_by_room[room]
            while t + timedelta(hours=duration) <= day_end:
                slot_end = t + timedelta(hours=duration) + timedelta(minutes=_TURNOVER_MINUTES)
                # Comprobar solapamiento con citas existentes y con no disponibilidad del especialista
                if (
                    not any(s < slot_end and e > t for s, e in occupied)
                    and not any(s < t + timedelta(hours=duration) and e > t for s, e in spec_unavail)
                ):
                    day_candidates.append((t, room))
                    break
                t += timedelta(minutes=30)

        for candidate in sorted(day_candidates, key=lambda x: x[0]):
            if len(slots) < n:
                slots.append(candidate)

        day += timedelta(days=1)
    return slots


def compute_pm_impact(df: pd.DataFrame) -> pd.DataFrame:
    """Simula 4 semanas de planificación de mañana por servicio (pizarra en blanco).
    Recibe el DataFrame actual y devuelve una tabla de impacto por servicio."""
    base = df.copy()
    base["Fecha_Intervencion"] = None
    base["Quirofano"]          = None

    today  = date.today()
    end    = today + timedelta(weeks=4)
    end_ts = pd.Timestamp(end)
    rows   = []
    for svc in sorted(base["Servicio"].dropna().unique()):
        svc_mask      = base["Servicio"] == svc
        n_unscheduled = int(svc_mask.sum())
        mean_duration = round(float(base.loc[svc_mask, "Duracion_Horas"].fillna(1).mean()), 2)

        df_sim, n_assigned = service_planning(base, svc, end, today, pm_room=None)

        n_rooms     = len(ROOMS_BY_SERVICE.get(svc, [])) or 1
        raw_impact  = (n_unscheduled - n_assigned) / n_rooms  # pacientes sin cubrir por OR de mañana

        svc_sim   = df_sim[df_sim["Servicio"] == svc].copy()
        _ingreso  = pd.to_datetime(svc_sim["Fecha_Ingreso"], errors="coerce")
        _interv   = pd.to_datetime(svc_sim["Fecha_Intervencion"], errors="coerce")
        wait_days = _interv.sub(_ingreso).dt.days.where(_interv.notna(), (end_ts - _ingreso).dt.days)
        mean_wait = round(float(wait_days.mean()), 1) if n_unscheduled > 0 else 0.0

        rows.append({
            "Servicio":        svc,
            "Sin cita":        n_unscheduled,
            "Asignados (M)":   n_assigned,
            "Dur. media (h)":  mean_duration,
            "Impacto cap.":    raw_impact,
            "Espera sim. (d)": mean_wait,
        })

    result = pd.DataFrame(rows)
    max_impact = result["Impacto cap."].max()
    if max_impact > 0:
        result["Impacto cap."] = (result["Impacto cap."] / max_impact).round(3)
    return result.sort_values("Espera sim. (d)", ascending=False)
