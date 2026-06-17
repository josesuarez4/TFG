import pandas as pd
from pathlib import Path
from datetime import date, datetime

_DATA_ROOT    = Path(__file__).parent.parent / "datos_generados" / "dashboard"
_CLOSED_PATH  = _DATA_ROOT / "dias_cerrados.csv"
_UNAVAIL_PATH = _DATA_ROOT / "especialistas_no_disponibles.csv"

_CLOSED_COLS  = ["quirofano", "fecha"]
_UNAVAIL_COLS = ["especialista_id", "especialista_nombre", "fecha", "hora_inicio", "hora_fin"]


# Días cerrados 

def load_closed_days_df() -> pd.DataFrame:
    if _CLOSED_PATH.exists():
        df = pd.read_csv(_CLOSED_PATH, dtype=str)
        return df[[c for c in _CLOSED_COLS if c in df.columns]].reindex(columns=_CLOSED_COLS, fill_value="")
    return pd.DataFrame(columns=_CLOSED_COLS)


def save_closed_days_for_rooms(rooms: list[str], rows: list[dict]) -> None:
    """Reemplaza las entradas del CSV para los quirófanos dados."""
    df = load_closed_days_df()
    df = df[~df["quirofano"].isin(rooms)]
    if rows:
        df = pd.concat([df, pd.DataFrame(rows, columns=_CLOSED_COLS)], ignore_index=True)
    _CLOSED_PATH.parent.mkdir(exist_ok=True)
    df.to_csv(_CLOSED_PATH, index=False)


def load_closed_days() -> dict[str, list[date]]:
    closed_by_room: dict[str, list[date]] = {}
    for _, row in load_closed_days_df().iterrows():
        parsed_date = pd.to_datetime(row["fecha"], errors="coerce")
        if pd.notna(parsed_date):
            closed_by_room.setdefault(str(row["quirofano"]), []).append(parsed_date.date())
    return closed_by_room


# Especialistas no disponibles

def load_unavailable_specs_df() -> pd.DataFrame:
    if _UNAVAIL_PATH.exists():
        df = pd.read_csv(_UNAVAIL_PATH, dtype=str)
        return df[[c for c in _UNAVAIL_COLS if c in df.columns]].reindex(columns=_UNAVAIL_COLS, fill_value="")
    return pd.DataFrame(columns=_UNAVAIL_COLS)


def save_unavailable_specs_for_ids(spec_ids: list[str], rows: list[dict]) -> None:
    """Reemplaza las entradas del CSV para los especialistas dados."""
    df = load_unavailable_specs_df()
    df = df[~df["especialista_id"].isin(spec_ids)]
    if rows:
        df = pd.concat([df, pd.DataFrame(rows, columns=_UNAVAIL_COLS)], ignore_index=True)
    _UNAVAIL_PATH.parent.mkdir(exist_ok=True)
    df.to_csv(_UNAVAIL_PATH, index=False)


def load_unavailable_specs() -> dict[str, list[tuple[datetime, datetime]]]:
    unavailable_by_spec: dict[str, list[tuple[datetime, datetime]]] = {}
    for _, row in load_unavailable_specs_df().iterrows():
        parsed_date = pd.to_datetime(row["fecha"], errors="coerce")
        if pd.isna(parsed_date):
            continue
        try:
            time_start = datetime.strptime(str(row["hora_inicio"]).strip(), "%H:%M")
            time_end   = datetime.strptime(str(row["hora_fin"]).strip(),    "%H:%M")
            unavailable_by_spec.setdefault(str(row["especialista_id"]), []).append((
                datetime(parsed_date.year, parsed_date.month, parsed_date.day, time_start.hour, time_start.minute),
                datetime(parsed_date.year, parsed_date.month, parsed_date.day, time_end.hour,   time_end.minute),
            ))
        except ValueError:
            pass
    return unavailable_by_spec
