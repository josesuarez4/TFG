from datetime import date
from pathlib import Path

import pandas as pd

CANCELLATIONS_PATH = Path(__file__).parent.parent / "datos_generados" / "dashboard" / "cancelaciones.csv"

_COLUMNS = ["fecha", "servicio", "id_paciente", "motivo"]


def save_cancellation(servicio: str, id_paciente: str, motivo: str = "") -> None:
    """Añade una fila al historial de cancelaciones."""
    row = {
        "fecha":       date.today().isoformat(),
        "servicio":    servicio,
        "id_paciente": id_paciente,
        "motivo":      motivo,
    }
    df = load_cancellations()
    df = pd.concat([df, pd.DataFrame([row])], ignore_index=True)
    CANCELLATIONS_PATH.parent.mkdir(exist_ok=True)
    df.to_csv(CANCELLATIONS_PATH, index=False, encoding="utf-8-sig")


def load_cancellations() -> pd.DataFrame:
    """Devuelve el historial completo de cancelaciones."""
    if CANCELLATIONS_PATH.exists():
        return pd.read_csv(CANCELLATIONS_PATH)
    return pd.DataFrame(columns=_COLUMNS)
