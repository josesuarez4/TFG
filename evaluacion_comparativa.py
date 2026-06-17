"""
Evaluación comparativa: planificación por prioridad vs. FIFO (orden de llegada).
"""

import os
import sys

_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_ROOT, "dashboard"))
sys.path.insert(0, _ROOT)

from datetime import date, datetime, timedelta

import pandas as pd

from planificador import _assign_slot, _TURNOVER_MINUTES

# Configuración 

SIM_WEEKS     = 12   # ventana de planificación simulada
HIGH_PRIO_PCT = 65   # percentil a partir del cual se considera "alta prioridad"

CSV_PATH = os.path.join(_ROOT, "datos_generados", "dashboard", "lista_espera_quirurgica.csv")


# Carga 

def load_clean_data() -> pd.DataFrame:
    """Carga el CSV sin citas existentes (simulación desde cero)."""
    df = pd.read_csv(CSV_PATH)
    df["Fecha_Intervencion"] = None
    df["Quirofano"]          = None
    return df


# Simulador 

def run_simulation(df_in: pd.DataFrame, strategy: str, start: date, end: date) -> pd.DataFrame:
    """
    Planifica todos los servicios con la estrategia indicada.

    strategy:
        "priority" — orden descendente por score de prioridad (cuadro de mando)
        "fifo"     — orden ascendente por fecha de ingreso (sistema convencional)
    """
    df = df_in.copy()
    df["Fecha_Intervencion"] = df["Fecha_Intervencion"].astype(object)
    df["Quirofano"]          = df["Quirofano"].astype(object)

    for service in sorted(df["Servicio"].dropna().unique()):
        service_mask = df["Servicio"] == service
        unscheduled  = df[service_mask & df["Fecha_Intervencion"].isna()].copy()

        if strategy == "priority":
            unscheduled = unscheduled.sort_values("Prioridad", ascending=False)
        else:
            unscheduled = unscheduled.sort_values("Fecha_Ingreso", ascending=True)

        used_slots: dict[str, list[tuple[datetime, datetime]]] = {}
        for _, row in df[df["Fecha_Intervencion"].notna()].iterrows():
            room       = str(row["Quirofano"])
            slot_start = pd.to_datetime(row["Fecha_Intervencion"]).to_pydatetime()
            duration   = float(row.get("Duracion_Horas") or 1.0)
            slot_end   = slot_start + timedelta(hours=duration) + timedelta(minutes=_TURNOVER_MINUTES)
            used_slots.setdefault(room, []).append((slot_start, slot_end))

        for idx, row in unscheduled.iterrows():
            admission = date.fromisoformat(str(row["Fecha_Ingreso"]))
            earliest  = max(admission + timedelta(days=14), start)
            if earliest > end:
                continue
            duration = float(row.get("Duracion_Horas") or 1.0)
            room, slot = _assign_slot(service, earliest, end, duration, used_slots)
            if room:
                df.loc[idx, "Fecha_Intervencion"] = slot
                df.loc[idx, "Quirofano"]          = room

    return df


# Métricas 

def compute_metrics(df: pd.DataFrame, high_prio_threshold: float) -> dict:
    """Calcula métricas de cobertura, espera y equidad sobre el resultado."""
    total     = len(df)
    scheduled = df[df["Fecha_Intervencion"].notna()].copy()

    scheduled["_interv"]  = pd.to_datetime(scheduled["Fecha_Intervencion"])
    scheduled["_ingreso"] = pd.to_datetime(scheduled["Fecha_Ingreso"])
    scheduled["_wait"]    = (scheduled["_interv"] - scheduled["_ingreso"]).dt.days

    high_prio_mask      = df["Prioridad"] >= high_prio_threshold
    high_prio_scheduled = scheduled[scheduled["Prioridad"] >= high_prio_threshold]
    low_prio_scheduled  = scheduled[scheduled["Prioridad"] <  high_prio_threshold]

    n_high          = int(high_prio_mask.sum())
    n_high_scheduled = len(high_prio_scheduled)
    n_low           = total - n_high
    n_low_scheduled  = len(low_prio_scheduled)

    wait_correlation = (
        scheduled[["Prioridad", "_wait"]].corr().loc["Prioridad", "_wait"]
        if len(scheduled) > 1 else 0.0
    )

    scheduled_sorted    = scheduled.sort_values("_interv")
    first_quartile      = scheduled_sorted.head(max(1, len(scheduled_sorted) // 4))
    pct_high_first_quartile = round(
        (first_quartile["Prioridad"] >= high_prio_threshold).sum() / len(first_quartile) * 100, 1
    ) if len(first_quartile) > 0 else 0.0

    return {
        "total":               total,
        "n_scheduled":         len(scheduled),
        "coverage_pct":        round(len(scheduled) / total * 100, 1),
        "n_high":              n_high,
        "n_high_scheduled":    n_high_scheduled,
        "cov_high_pct":        round(n_high_scheduled / n_high * 100, 1) if n_high > 0 else 0.0,
        "mean_wait_high":      round(high_prio_scheduled["_wait"].mean(), 1)   if n_high_scheduled > 0 else None,
        "median_wait_high":    round(high_prio_scheduled["_wait"].median(), 1) if n_high_scheduled > 0 else None,
        "n_low_scheduled":     n_low_scheduled,
        "cov_low_pct":         round(n_low_scheduled / n_low * 100, 1) if n_low > 0 else 0.0,
        "mean_wait_low":       round(low_prio_scheduled["_wait"].mean(), 1) if n_low_scheduled > 0 else None,
        "mean_wait":           round(scheduled["_wait"].mean(), 1)   if len(scheduled) > 0 else None,
        "median_wait":         round(scheduled["_wait"].median(), 1) if len(scheduled) > 0 else None,
        "std_wait":            round(scheduled["_wait"].std(), 1)    if len(scheduled) > 0 else None,
        "total_or_hours":      round(scheduled["Duracion_Horas"].fillna(1).sum(), 1),
        "corr_prio_wait":      round(wait_correlation, 3),
        "pct_high_in_first_q": pct_high_first_quartile,
    }


# Guardado 

def format_value(val, decimals: int = 1) -> str:
    if val is None:
        return "—"
    if isinstance(val, float):
        return f"{val:.{decimals}f}"
    return str(val)


def save_results(metrics_fifo: dict, metrics_prio: dict,
                 start: date, end: date, high_threshold: float) -> None:
    """Guarda un fichero TXT con las tablas de resultados más relevantes."""

    def build_table(headers: list[str], rows: list[list[str]], widths: list[int]) -> list[str]:
        def divider(left, mid, right):
            return left + mid.join("─" * (w + 2) for w in widths) + right
        def data_row(cells):
            parts = [f" {c:<{w}} " if i == 0 else f" {c:>{w}} "
                     for i, (c, w) in enumerate(zip(cells, widths))]
            return "│" + "│".join(parts) + "│"
        table_lines = [divider("┌", "┬", "┐"), data_row(headers), divider("├", "┼", "┤")]
        for i, row in enumerate(rows):
            table_lines.append(data_row(row))
            table_lines.append(
                divider("├", "┼", "┤") if i < len(rows) - 1 else divider("└", "┴", "┘")
            )
        return table_lines

    def compute_delta(fifo_val, prio_val, unit="", dec=1):
        if fifo_val is None or prio_val is None:
            return "—"
        diff = round(prio_val - fifo_val, dec)
        return f"{'+'if diff > 0 else ''}{diff:.{dec}f}{unit}"

    lines: list[str] = [
        "EVALUACIÓN COMPARATIVA — CUADRO DE MANDO QUIRÚRGICO",
        f"Simulación: {start.strftime('%d/%m/%Y')} – {end.strftime('%d/%m/%Y')} "
        f"({SIM_WEEKS} sem.)  |  {metrics_fifo['total']:,} pacientes  |  "
        f"Alta prioridad ≥ P{HIGH_PRIO_PCT} (score ≥ {high_threshold:.1f} %, {metrics_fifo['n_high']:,} pac.)",
        "",
    ]

    # Tabla 1: FIFO vs Prioridad 
    lines += build_table(
        ["Métrica", "FIFO", "Prioridad", " (Prio − FIFO)"],
        [
            ["Cobertura global (%)",
             f"{metrics_fifo['coverage_pct']} %", f"{metrics_prio['coverage_pct']} %",
             compute_delta(metrics_fifo["coverage_pct"], metrics_prio["coverage_pct"], " %")],

            ["Horas quirúrgicas totales (h)",
             f"{format_value(metrics_fifo['total_or_hours'])} h",
             f"{format_value(metrics_prio['total_or_hours'])} h",
             compute_delta(metrics_fifo["total_or_hours"], metrics_prio["total_or_hours"], " h")],

            ["Cobertura alta prioridad (%)",
             f"{metrics_fifo['cov_high_pct']} %", f"{metrics_prio['cov_high_pct']} %",
             compute_delta(metrics_fifo["cov_high_pct"], metrics_prio["cov_high_pct"], " %")],

            ["Espera media alta prioridad (días)",
             f"{format_value(metrics_fifo['mean_wait_high'])} d",
             f"{format_value(metrics_prio['mean_wait_high'])} d",
             compute_delta(metrics_fifo["mean_wait_high"], metrics_prio["mean_wait_high"], " d")],

            ["Mediana espera alta prioridad (días)",
             f"{format_value(metrics_fifo['median_wait_high'])} d",
             f"{format_value(metrics_prio['median_wait_high'])} d",
             compute_delta(metrics_fifo["median_wait_high"], metrics_prio["median_wait_high"], " d")],

            ["Espera media global (días)",
             f"{format_value(metrics_fifo['mean_wait'])} d",
             f"{format_value(metrics_prio['mean_wait'])} d",
             compute_delta(metrics_fifo["mean_wait"], metrics_prio["mean_wait"], " d")],

            ["Desv. estándar espera (días)",
             f"{format_value(metrics_fifo['std_wait'])} d",
             f"{format_value(metrics_prio['std_wait'])} d",
             compute_delta(metrics_fifo["std_wait"], metrics_prio["std_wait"], " d")],

            ["Correlación prioridad–espera",
             format_value(metrics_fifo["corr_prio_wait"], 3),
             format_value(metrics_prio["corr_prio_wait"], 3),
             compute_delta(metrics_fifo["corr_prio_wait"], metrics_prio["corr_prio_wait"], dec=3)],

            ["Pacientes de alta prior. atendidos primero (%)",
             f"{metrics_fifo['pct_high_in_first_q']} %",
             f"{metrics_prio['pct_high_in_first_q']} %",
             compute_delta(metrics_fifo["pct_high_in_first_q"], metrics_prio["pct_high_in_first_q"], " %")],
        ],
        [46, 12, 12, 16],
    )

    output_path = os.path.join(_ROOT, "datos_generados", "dashboard", "resultados_evaluacion.txt")
    with open(output_path, "w", encoding="utf-8") as file:
        file.write("\n".join(lines) + "\n")

    print(f"Guardado: {output_path}")


# Main 

if __name__ == "__main__":
    start_date = date.today()
    end_date   = start_date + timedelta(weeks=SIM_WEEKS)

    high_threshold = pd.read_csv(CSV_PATH)["Prioridad"].quantile(HIGH_PRIO_PCT / 100)

    df_clean = load_clean_data()
    df_fifo  = run_simulation(df_clean.copy(), "fifo",     start_date, end_date)
    df_prio  = run_simulation(df_clean.copy(), "priority", start_date, end_date)

    metrics_fifo = compute_metrics(df_fifo, high_threshold)
    metrics_prio = compute_metrics(df_prio, high_threshold)

    save_results(metrics_fifo, metrics_prio, start_date, end_date, high_threshold)
