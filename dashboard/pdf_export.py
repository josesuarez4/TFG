"""Generación de PDF con la planificación quirúrgica de un servicio."""

from datetime import date

import pandas as pd
from fpdf import FPDF

_FONT_R = "/usr/share/fonts/truetype/ubuntu/Ubuntu-R.ttf"
_FONT_B = "/usr/share/fonts/truetype/ubuntu/Ubuntu-B.ttf"

# Márgenes y ancho útil (A4 landscape: 297 × 210 mm)
_MARGIN   = 15
_PAGE_W   = 297
_USABLE_W = _PAGE_W - 2 * _MARGIN  # 267 mm

# Anchos de columna (suman 267 mm)
_COL_WIDTHS = {
    "Fecha y hora":  42,
    "ID Paciente":   68,
    "Duracion (h)":  20,
    "Procedimiento": 102,
    "Prioridad (%)": 35,
}

_HEADER_COLOR = (41, 128, 185)
_ROW_ALT      = (235, 245, 255)
_ROOM_COLOR   = (52, 73, 94)


class _PlanPDF(FPDF):
    def __init__(self, service: str, period_start: date, period_end: date):
        super().__init__(orientation="L", unit="mm", format="A4")
        self.service      = service
        self.period_start = period_start
        self.period_end   = period_end
        self.set_margins(_MARGIN, _MARGIN, _MARGIN)
        self.set_auto_page_break(auto=True, margin=_MARGIN)
        # Registrar fuentes Unicode
        self.add_font("Ubuntu",  style="",  fname=_FONT_R)
        self.add_font("Ubuntu",  style="B", fname=_FONT_B)

    def header(self):
        self.set_font("Ubuntu", "B", 11)
        self.set_text_color(60, 60, 60)
        self.cell(0, 8, f"Planificacion quirurgica - {self.service}", align="L")
        self.set_font("Ubuntu", "", 9)
        period    = f"{self.period_start.strftime('%d/%m/%Y')} - {self.period_end.strftime('%d/%m/%Y')}"
        generated = f"Generado: {date.today().strftime('%d/%m/%Y')}"
        self.cell(0, 8, f"{period}   |   {generated}", align="R")
        self.ln(2)
        self.set_draw_color(*_HEADER_COLOR)
        self.set_line_width(0.5)
        self.line(_MARGIN, self.get_y(), _PAGE_W - _MARGIN, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-12)
        self.set_font("Ubuntu", "", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, f"Pagina {self.page_no()}", align="C")

    def _table_header(self):
        self.set_fill_color(*_HEADER_COLOR)
        self.set_text_color(255, 255, 255)
        self.set_font("Ubuntu", "B", 8)
        for col, w in _COL_WIDTHS.items():
            self.cell(w, 7, col, border=0, align="C", fill=True)
        self.ln()
        self.set_text_color(0, 0, 0)

    def add_room_section(self, room: str, rows: list[dict]):
        if self.get_y() > 170:
            self.add_page()

        # Cabecera del quirofano
        self.set_fill_color(*_ROOM_COLOR)
        self.set_text_color(255, 255, 255)
        self.set_font("Ubuntu", "B", 9)
        self.cell(_USABLE_W, 7, f"  Quirofano: {room}  ({len(rows)} intervenciones)", fill=True)
        self.ln()

        self._table_header()

        self.set_font("Ubuntu", "", 8)
        for i, row in enumerate(rows):
            if self.get_y() > 185:
                self.add_page()
                self._table_header()
            fill = i % 2 == 1
            self.set_fill_color(*_ROW_ALT)
            self.set_text_color(0, 0, 0)

            # Truncar procedimiento si no cabe
            proc = str(row["procedimiento"])
            max_w = _COL_WIDTHS["Procedimiento"] - 2
            while self.get_string_width(proc) > max_w and len(proc) > 0:
                proc = proc[:-1]
            if len(proc) < len(str(row["procedimiento"])):
                proc = proc[:-1] + "..."

            self.cell(_COL_WIDTHS["Fecha y hora"],  6, str(row["fecha"]),      border=0, align="C", fill=fill)
            self.cell(_COL_WIDTHS["ID Paciente"],   6, str(row["id"]),         border=0, fill=fill)
            self.cell(_COL_WIDTHS["Duracion (h)"],  6, str(row["duracion"]),   border=0, align="C", fill=fill)
            self.cell(_COL_WIDTHS["Procedimiento"], 6, proc,                   border=0, fill=fill)
            self.cell(_COL_WIDTHS["Prioridad (%)"], 6, str(row["prioridad"]),  border=0, align="C", fill=fill)
            self.ln()

        self.ln(3)


def build_pdf(
    df: pd.DataFrame,
    service: str,
    period_start: date,
    period_end: date,
) -> bytes:
    """Genera el PDF y devuelve los bytes para la descarga."""
    mask = (
        (df["Servicio"] == service)
        & df["Fecha_Intervencion"].notna()
    )
    subset = df[mask].copy()
    subset["_dt"] = pd.to_datetime(subset["Fecha_Intervencion"], errors="coerce")
    subset = subset[
        (subset["_dt"].dt.date >= period_start)
        & (subset["_dt"].dt.date <= period_end)
    ].sort_values("_dt")

    pdf = _PlanPDF(service, period_start, period_end)
    pdf.add_page()

    if subset.empty:
        pdf.set_font("Ubuntu", "", 10)
        pdf.cell(0, 10, "No hay intervenciones planificadas en el periodo seleccionado.", align="C")
        return bytes(pdf.output())

    for room, grp in subset.groupby("Quirofano"):
        rows = [
            {
                "fecha":        row["_dt"].strftime("%d/%m/%Y %H:%M"),
                "id":           str(row["ID_Paciente"]),
                "duracion":     f"{float(row.get('Duracion_Horas') or 1):.1f}",
                "procedimiento": str(row.get("Descripcion_Procedimiento", "")),
                "prioridad":    f"{float(row['Prioridad']):.1f}%",
            }
            for _, row in grp.iterrows()
        ]
        pdf.add_room_section(str(room), rows)

    # Totales al pie
    pdf.set_font("Ubuntu", "", 8)
    pdf.set_text_color(100, 100, 100)
    total_h = subset["Duracion_Horas"].fillna(1).sum()
    pdf.cell(
        0, 6,
        f"Total intervenciones: {len(subset)}   |   Horas quirurgicas totales: {total_h:.1f} h",
        align="R",
    )

    return bytes(pdf.output())
