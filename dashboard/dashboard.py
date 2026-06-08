import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))  # permite importar prioridad.py desde la raíz

import os
from datetime import date, datetime, timedelta
import streamlit as st
import pandas as pd
import plotly.express as px
from streamlit_calendar import calendar as st_calendar
from quirofanos import ROOMS_BY_SERVICE
from prioridad import calculate_priority
from especialistas import specialists_for_service, SPECIALISTS_BY_ROOM
from huecos import save_gap, load_gaps, find_candidates, remove_gap
from quirofanos_tarde import TARDE_ROOMS, load_tarde_assignment, save_tarde_assignment
from planificador import service_planning
from restricciones import (
    load_closed_days_df, save_closed_days_for_rooms, load_closed_days,
    load_unavailable_specs_df, save_unavailable_specs_for_ids, load_unavailable_specs,
)

st.set_page_config(page_title="Dashboard Lista de Espera", layout="wide")


@st.dialog("Información del paciente", width="large")
def _show_patient_dialog(patient: pd.Series) -> None:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ID",             str(patient["ID_Paciente"])[:12])
    c2.metric("Edad",           f"{int(patient['Edad'])} años")
    c3.metric("Sexo",           str(patient.get("Sexo", "—")))
    c4.metric("Prioridad",      f"{float(patient['Prioridad']):.1f}%")

    st.markdown("---")
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Servicio**")
        st.write(patient.get("Servicio", "—"))
        st.markdown("**Tipo de cirugía**")
        st.write(patient.get("Tipo_Cirugia", "—"))
        st.markdown("**Fecha de ingreso**")
        st.write(str(patient.get("Fecha_Ingreso", "—"))[:10])
    with col_b:
        st.markdown("**Diagnóstico**")
        st.write(f"{patient.get('Codigo_Diagnostico_1','—')} — {patient.get('Descripcion_Diagnostico_1','')}")
        st.markdown("**Procedimiento**")
        st.write(f"{patient.get('Codigo_Procedimiento','—')} — {patient.get('Descripcion_Procedimiento','')}")

    if pd.notna(patient.get("Comorbilidades")) and str(patient.get("Comorbilidades", "")).strip():
        st.markdown("---")
        st.markdown("**Comorbilidades**")
        st.write(patient["Comorbilidades"])

CSV_PATH = str(Path(__file__).parent.parent / "datos_generados" / "lista_espera_quirurgica.csv")

_TURNOVER_MIN = 30


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
    closed_days      = closed_days or {}
    unavailable_specs = unavailable_specs or {}

    # Precomputar slots ocupados por quirófano
    occupied_by_room: dict[str, list[tuple[datetime, datetime]]] = {}
    for room in rooms:
        room_rows = df_current[df_current["Quirofano"] == room].copy()
        room_rows["_s"] = pd.to_datetime(room_rows["Fecha_Intervencion"], errors="coerce")
        room_rows["_e"] = room_rows["_s"] + pd.to_timedelta(
            room_rows["Duracion_Horas"].fillna(1), unit="h"
        ) + timedelta(minutes=_TURNOVER_MIN)
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
                slot_end = t + timedelta(hours=duration) + timedelta(minutes=_TURNOVER_MIN)
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


@st.cache_data
def load_data(mtime: float):
    return pd.read_csv(CSV_PATH)


def _compute_tarde_impact() -> pd.DataFrame:
    """Simula 4 semanas de planificación de mañana por servicio (pizarra en blanco).
    No usa caché — se llama solo al inicio o cuando el usuario lo solicita."""
    _df_base = pd.read_csv(CSV_PATH)
    _df_base["Fecha_Intervencion"] = None
    _df_base["Quirofano"]          = None

    today  = date.today()
    end    = today + timedelta(weeks=4)
    end_ts = pd.Timestamp(end)
    rows   = []
    for svc in sorted(_df_base["Servicio"].dropna().unique()):
        svc_mask   = _df_base["Servicio"] == svc
        n_unscheduled = int(svc_mask.sum())
        mean_duration  = round(float(_df_base.loc[svc_mask, "Duracion_Horas"].fillna(1).mean()), 2)

        df_sim, n_assigned = service_planning(_df_base, svc, end, today, tarde_room=None)

        uncovered_ratio = (n_unscheduled - n_assigned) / n_unscheduled if n_unscheduled > 0 else 0.0
        capacity_impact = round(uncovered_ratio * mean_duration, 3)

        svc_sim  = df_sim[df_sim["Servicio"] == svc].copy()
        _ingreso = pd.to_datetime(svc_sim["Fecha_Ingreso"], errors="coerce")
        _interv  = pd.to_datetime(svc_sim["Fecha_Intervencion"], errors="coerce")
        wait_days   = _interv.sub(_ingreso).dt.days.where(_interv.notna(), (end_ts - _ingreso).dt.days)
        mean_wait = round(float(wait_days.mean()), 1) if n_unscheduled > 0 else 0.0

        rows.append({
            "Servicio":        svc,
            "Sin cita":        n_unscheduled,
            "Asignados (M)":   n_assigned,
            "Dur. media (h)":  mean_duration,
            "Impacto cap.":    capacity_impact,
            "Espera sim. (d)": mean_wait,
        })
    return pd.DataFrame(rows).sort_values("Espera sim. (d)", ascending=False)


df = load_data(os.path.getmtime(CSV_PATH))

# Precalcular Dias_Espera sobre el dataset completo (necesario para el filtro de tramo)
_today = date.today()
_ingreso_dt = pd.to_datetime(df["Fecha_Ingreso"])
_interv_dt  = pd.to_datetime(df["Fecha_Intervencion"], errors="coerce")
_sched_all  = df["Fecha_Intervencion"].notna()
df["Dias_Espera"] = (pd.Timestamp(_today) - _ingreso_dt).dt.days
df.loc[_sched_all, "Dias_Espera"] = (_interv_dt[_sched_all] - _ingreso_dt[_sched_all]).dt.days

st.title("Dashboard de lista de espera quirúrgica")

_TRAMO_BINS = {
    "< 30 d":   (0,   30),
    "30–60 d":  (30,  60),
    "60–90 d":  (60,  90),
    "90–180 d": (90,  180),
    "> 180 d":  (180, 99_999),
}

# KPIs generales (Tab 1 — dataset completo, sin filtros)
_sched_g     = df["Fecha_Intervencion"].notna()
_n_espera_g  = int((~_sched_g).sum())
_dem_media_g = df["Dias_Espera"].mean()
_dem_max_g   = int(df["Dias_Espera"].max())
_edad_esp_g  = df.loc[~_sched_g, "Edad"].mean() if _n_espera_g > 0 else None
_hp_g        = df["Prioridad"] >= 70
_indice_g    = ((df.loc[_hp_g & _sched_g, "Dias_Espera"] <= 90).sum() / _hp_g.sum() * 100) if _hp_g.sum() > 0 else None
_df_g        = df.copy()

tab1, tab2, tab3, tab4 = st.tabs(["Resumen", "Análisis", "Pacientes", "Planificación"])

# ── TAB 1: RESUMEN ────────────────────────────────────────────────────────────
with tab1:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Pacientes",      len(df))
    col2.metric("Edad media",     f"{df['Edad'].mean():.1f}")
    col3.metric("Servicios",      df["Servicio"].nunique())
    col4.metric("Prioridad media", f"{df['Prioridad'].mean():.1f}%")

    st.markdown("---")

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Sin cita",            _n_espera_g)
    k2.metric("Demora media",        f"{_dem_media_g:.0f} d")
    k3.metric("Demora máxima",       f"{_dem_max_g} d")
    k4.metric("Edad media (espera)", f"{_edad_esp_g:.1f}" if _edad_esp_g is not None else "—")
    k5.metric("Alta prior. ≤90 d",   f"{_indice_g:.0f}%"  if _indice_g  is not None else "—")

    st.markdown("---")

    g1, g2, g3 = st.columns(3)
    with g1:
        wait_by_svc = (
            _df_g.groupby("Servicio")["Dias_Espera"]
            .mean().reset_index()
            .sort_values("Dias_Espera", ascending=True)
        )
        wait_by_svc.columns = ["Servicio", "Media"]
        fig = px.bar(
            wait_by_svc, x="Media", y="Servicio", orientation="h",
            title="Tiempo de espera medio por servicio",
            labels={"Media": "Días", "Servicio": ""},
            text=wait_by_svc["Media"].round(0).fillna(0).astype(int),
            color="Media", color_continuous_scale="Oranges",
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(coloraxis_showscale=False, margin={"l": 220})
        st.plotly_chart(fig, use_container_width=True)

    with g2:
        count = df["Servicio"].value_counts().reset_index()
        count.columns = ["Servicio", "Pacientes"]
        fig = px.bar(count, x="Servicio", y="Pacientes", title="Pacientes por servicio",
                     color="Pacientes", color_continuous_scale="Blues")
        fig.update_layout(showlegend=False, coloraxis_showscale=False, xaxis_tickangle=-35)
        st.plotly_chart(fig, use_container_width=True)

    with g3:
        fig = px.histogram(df, x="Prioridad", nbins=20,
                           title="Distribución de prioridad",
                           labels={"Prioridad": "Prioridad (%)"},
                           color_discrete_sequence=["#e74c3c"])
        fig.update_layout(bargap=0.05, xaxis_range=[0, 100])
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    r1, r2 = st.columns(2)

    with r1:
        df_occ_g = df[df["Fecha_Intervencion"].notna()].copy()
        if not df_occ_g.empty:
            df_occ_g["_interv_dt"] = pd.to_datetime(df_occ_g["Fecha_Intervencion"], format="mixed", errors="coerce")
            occ_rows = []
            for _svc, _grp in df_occ_g.groupby("Servicio"):
                _n_rooms = len(ROOMS_BY_SERVICE.get(_svc, []))
                if _n_rooms == 0:
                    continue
                _surgery_days = _grp["_interv_dt"].dt.date.nunique()
                _avail_h      = _n_rooms * _surgery_days * 8
                _used_h       = _grp["Duracion_Horas"].fillna(0).sum()
                occ_rows.append({
                    "Servicio":      _svc,
                    "Ocupación (%)": round(min(_used_h / _avail_h * 100, 100), 1) if _avail_h > 0 else 0,
                    "Horas usadas":  round(_used_h, 1),
                })
            occ_df = pd.DataFrame(occ_rows).sort_values("Ocupación (%)", ascending=True)
            fig_occ = px.bar(
                occ_df, x="Ocupación (%)", y="Servicio", orientation="h",
                title="Utilización de quirófanos por servicio",
                labels={"Ocupación (%)": "Ocupación (%)", "Servicio": ""},
                text="Ocupación (%)",
                color="Ocupación (%)", color_continuous_scale="Blues",
                custom_data=["Horas usadas"],
            )
            fig_occ.update_traces(
                texttemplate="%{text:.1f}%", textposition="outside",
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    "Ocupación: %{x:.1f}%<br>"
                    "Horas programadas: %{customdata[0]:.1f} h<extra></extra>"
                ),
            )
            fig_occ.update_layout(coloraxis_showscale=False, margin={"l": 220}, xaxis_range=[0, 110])
            st.plotly_chart(fig_occ, use_container_width=True)
        else:
            st.info("Sin intervenciones planificadas — planifica un servicio para ver la ocupación.")

    with r2:
        ratio_df = df.groupby("Servicio").agg(
            Con_cita=("Fecha_Intervencion", lambda x: x.notna().sum()),
            Sin_cita=("Fecha_Intervencion", lambda x: x.isna().sum()),
        ).reset_index()
        ratio_melted = ratio_df.melt(
            id_vars="Servicio", value_vars=["Con_cita", "Sin_cita"],
            var_name="Estado", value_name="Pacientes",
        )
        ratio_melted["Estado"] = ratio_melted["Estado"].map({"Con_cita": "Con cita", "Sin_cita": "Sin cita"})
        fig_ratio = px.bar(
            ratio_melted, x="Servicio", y="Pacientes", color="Estado",
            title="Cobertura de planificación por servicio",
            color_discrete_map={"Con cita": "#2ecc71", "Sin cita": "#e74c3c"},
            barmode="stack",
        )
        fig_ratio.update_layout(xaxis_tickangle=-35, legend_title_text="")
        st.plotly_chart(fig_ratio, use_container_width=True)

    st.markdown("---")

    fig_box = px.box(
        df, x="Servicio", y="Dias_Espera",
        title="Distribución de días de espera por servicio",
        labels={"Dias_Espera": "Días de espera", "Servicio": ""},
        color="Servicio",
        points="outliers",
    )
    fig_box.update_layout(showlegend=False, xaxis_tickangle=-35)
    st.plotly_chart(fig_box, use_container_width=True)

# ── TAB 2: ANÁLISIS ──────────────────────────────────────────────────────────
@st.fragment
def _tab2_fn():
    # Filtros inline
    f1, f2, f3, f4 = st.columns([2, 2, 1, 1])
    with f1:
        selected_service = st.selectbox("Servicio", options=sorted(df["Servicio"].dropna().unique()), key="ana_svc")
    with f2:
        prio_min, prio_max = st.slider("Rango de prioridad (%)", 0, 100, (0, 100), step=1, key="ana_prio")
    with f3:
        estado_cita = st.selectbox("Estado de cita", options=["Todos", "Sin cita", "Con cita"], key="ana_estado")
    with f4:
        tramo_sel = st.selectbox("Tramo de espera", options=["Todos"] + list(_TRAMO_BINS), key="ana_tramo")

    # Computar máscaras y dataset filtrado
    _svc_mask = df["Servicio"] == selected_service
    _prio_mask = df["Prioridad"].between(prio_min, prio_max)
    _estado_mask = (
        df["Fecha_Intervencion"].isna()  if estado_cita == "Sin cita"  else
        df["Fecha_Intervencion"].notna() if estado_cita == "Con cita"  else
        pd.Series(True, index=df.index)
    )
    if tramo_sel != "Todos":
        _lo, _hi   = _TRAMO_BINS[tramo_sel]
        _tramo_mask = df["Dias_Espera"].between(_lo, _hi - 1)
    else:
        _tramo_mask = pd.Series(True, index=df.index)
    df_filtered = df[_svc_mask & _prio_mask & _estado_mask & _tramo_mask]
    _df = df_filtered.copy() if not df_filtered.empty else None

    # KPIs del servicio seleccionado
    _svc_all   = df[df["Servicio"] == selected_service]
    _svc_sched = _svc_all["Fecha_Intervencion"].notna()
    _svc_n     = len(_svc_all)
    _svc_pct   = _svc_sched.sum() / _svc_n * 100 if _svc_n > 0 else 0
    _svc_dem   = _svc_all["Dias_Espera"].mean()
    _svc_dem_max = int(_svc_all["Dias_Espera"].max())
    _svc_prio  = _svc_all["Prioridad"].mean()
    _svc_hp    = _svc_all["Prioridad"] >= 70
    _svc_idx   = (
        (_svc_all.loc[_svc_hp & _svc_sched, "Dias_Espera"] <= 90).sum() / _svc_hp.sum() * 100
        if _svc_hp.sum() > 0 else None
    )
    st.markdown("---")
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Pacientes en servicio", _svc_n)
    k2.metric("Con cita asignada",     f"{_svc_pct:.0f}%")
    k3.metric("Demora media",          f"{_svc_dem:.0f} d")
    k4.metric("Demora máxima",         f"{_svc_dem_max} d")
    k5.metric("Prioridad media",       f"{_svc_prio:.1f}%")
    k6.metric("Alta prior. ≤90 d",     f"{_svc_idx:.0f}%" if _svc_idx is not None else "—")

    st.markdown("---")

    # ── Fila 1: scatter · tramos · horas semanales ────────────────────────────
    r1c1, r1c2, r1c3 = st.columns(3)

    with r1c1:
        scatter_threshold = st.number_input(
            "Umbral alta prioridad (%)", min_value=0, max_value=100, value=70, step=5, key="scatter_threshold",
        )
        if _df is not None:
            fig_scatter = px.scatter(
                _df, x="Dias_Espera", y="Prioridad",
                title="Prioridad vs. días de espera",
                labels={"Dias_Espera": "Días en espera", "Prioridad": "Prioridad (%)"},
                hover_data=["ID_Paciente", "Descripcion_Diagnostico_1"],
                opacity=0.6,
                color_discrete_sequence=["#3788d8"],
            )
            fig_scatter.add_hline(
                y=scatter_threshold, line_dash="dash", line_color="red",
                annotation_text=f"Alta prioridad ({scatter_threshold})", annotation_position="top right",
            )
            st.plotly_chart(fig_scatter, use_container_width=True)
        else:
            st.info("Sin datos para este filtro.")

    with r1c2:
        if _df is not None:
            _bins   = [0, 30, 60, 90, 180, 10_000]
            _labels = ["< 30 d", "30–60 d", "60–90 d", "90–180 d", "> 180 d"]
            _tramos = _df.copy()
            _tramos["Tramo"] = pd.cut(_tramos["Dias_Espera"], bins=_bins, labels=_labels, right=False)
            tramo_counts = _tramos["Tramo"].value_counts().reindex(_labels).fillna(0).reset_index()
            tramo_counts.columns = ["Tramo", "Pacientes"]
            tramo_counts["Pct"] = (tramo_counts["Pacientes"] / tramo_counts["Pacientes"].sum() * 100).round(1)
            fig_tramos = px.bar(
                tramo_counts, x="Tramo", y="Pacientes",
                title="Pacientes por tramo de espera",
                text=tramo_counts["Pct"].apply(lambda v: f"{v:.1f}%"),
                color="Tramo",
                color_discrete_sequence=px.colors.sequential.Oranges[2:],
            )
            fig_tramos.update_traces(textposition="outside")
            fig_tramos.update_layout(showlegend=False)
            st.plotly_chart(fig_tramos, use_container_width=True)
        else:
            st.info("Sin datos para este filtro.")

    with r1c3:
        df_sched_wk = df_filtered[df_filtered["Fecha_Intervencion"].notna()].copy()
        if not df_sched_wk.empty:
            df_sched_wk["_week"] = (
                pd.to_datetime(df_sched_wk["Fecha_Intervencion"], format="mixed").dt.to_period("W").dt.start_time
            )
            weekly = df_sched_wk.groupby("_week")["Duracion_Horas"].sum().reset_index()
            weekly.columns = ["Semana", "Horas"]
            fig_wk = px.line(
                weekly, x="Semana", y="Horas",
                title="Horas quirúrgicas por semana",
                labels={"Horas": "Horas programadas"},
                markers=True,
                color_discrete_sequence=["#3788d8"],
            )
            st.plotly_chart(fig_wk, use_container_width=True)
        else:
            st.info("Sin intervenciones planificadas.")

    st.markdown("---")

    # ── Fila 2: edad · tipo cirugía · alta prioridad sin cita ─────────────────
    r2c1, r2c2, r2c3 = st.columns(3)

    with r2c1:
        if _df is not None:
            fig_age = px.histogram(
                _df, x="Edad", nbins=20,
                title="Distribución de edad",
                labels={"Edad": "Edad (años)", "count": "Pacientes"},
                opacity=0.8,
                color_discrete_sequence=["#3788d8"],
            )
            fig_age.update_layout(bargap=0.05, showlegend=False)
            st.plotly_chart(fig_age, use_container_width=True)
        else:
            st.info("Sin datos para este filtro.")

    with r2c2:
        if _df is not None:
            _tipo = _df.copy()
            _tipo["Estado"] = _tipo["Fecha_Intervencion"].apply(
                lambda x: "Con cita" if pd.notna(x) else "Sin cita"
            )
            tipo_counts = (
                _tipo.groupby(["Tipo_Cirugia", "Estado"])
                .size().reset_index(name="Pacientes")
            )
            fig_tipo = px.bar(
                tipo_counts, x="Tipo_Cirugia", y="Pacientes", color="Estado",
                title="Tipo de cirugía: cobertura",
                labels={"Tipo_Cirugia": "Tipo de cirugía"},
                color_discrete_map={"Con cita": "#2ecc71", "Sin cita": "#e74c3c"},
                barmode="stack",
            )
            fig_tipo.update_layout(xaxis_tickangle=-25, legend_title_text="")
            st.plotly_chart(fig_tipo, use_container_width=True)
        else:
            st.info("Sin datos para este filtro.")

    with r2c3:
        hp_threshold = st.number_input(
            "Prioridad mínima (%)", min_value=0, max_value=100, value=60, step=5, key="hp_threshold",
        )
        if _df is not None:
            _hp_sin = _df[(_df["Prioridad"] >= hp_threshold) & _df["Fecha_Intervencion"].isna()].copy()
            if not _hp_sin.empty:
                _bins2   = [0, 30, 60, 90, 180, 10_000]
                _labels2 = ["< 30 d", "30–60 d", "60–90 d", "90–180 d", "> 180 d"]
                _hp_sin["Tramo"] = pd.cut(_hp_sin["Dias_Espera"], bins=_bins2, labels=_labels2, right=False)
                hp_counts = _hp_sin["Tramo"].value_counts().reindex(_labels2).fillna(0).reset_index()
                hp_counts.columns = ["Tramo", "Pacientes"]
                fig_hp = px.bar(
                    hp_counts, x="Tramo", y="Pacientes",
                    title=f"Prioridad ≥{hp_threshold}% sin cita por tramo",
                    labels={"Tramo": "Tramo de espera"},
                    text="Pacientes",
                    color="Tramo",
                    color_discrete_sequence=px.colors.sequential.Reds[2:],
                )
                fig_hp.update_traces(textposition="outside")
                fig_hp.update_layout(showlegend=False)
                st.plotly_chart(fig_hp, use_container_width=True)
            else:
                st.info(f"No hay pacientes con prioridad ≥{hp_threshold}% sin cita.")
        else:
            st.info("Sin datos para este filtro.")

    st.markdown("---")

    # ── Heatmap de carga quirúrgica: quirófano × día de la semana ─────────────
    df_heat = df_filtered[df_filtered["Fecha_Intervencion"].notna()].copy()
    if not df_heat.empty:
        _dias_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
        df_heat["_dow"]  = pd.to_datetime(df_heat["Fecha_Intervencion"], format="mixed").dt.dayofweek
        df_heat["_dow"]  = df_heat["_dow"].map({0:"Lunes",1:"Martes",2:"Miércoles",3:"Jueves",4:"Viernes"})
        df_heat = df_heat[df_heat["_dow"].notna()]
        heat_pivot = (
            df_heat.groupby(["Quirofano", "_dow"])["Duracion_Horas"]
            .sum().reset_index()
            .pivot(index="Quirofano", columns="_dow", values="Duracion_Horas")
            .reindex(columns=_dias_es)
            .fillna(0)
        )
        if not heat_pivot.empty:
            fig_heat = px.imshow(
                heat_pivot,
                title="Horas quirúrgicas por quirófano y día de la semana",
                labels={"x": "Día", "y": "Quirófano", "color": "Horas"},
                color_continuous_scale="Blues",
                text_auto=".1f",
                aspect="auto",
            )
            fig_heat.update_layout(xaxis_title="", yaxis_title="")
            st.plotly_chart(fig_heat, use_container_width=True)
        else:
            st.info("Sin datos suficientes para el heatmap.")
    else:
        st.info("Sin intervenciones planificadas.")


with tab2:
    _tab2_fn()

# ── TAB 3: PACIENTES ──────────────────────────────────────────────────────────
@st.fragment
def _tab3_fn():
    # Contadores para forzar reset de los inputs tras confirmar acción
    if "cancel_id_v" not in st.session_state:
        st.session_state["cancel_id_v"] = 0
    if "man_id_v" not in st.session_state:
        st.session_state["man_id_v"] = 0

    _t3_cancel_col, _t3_assign_col = st.columns(2)

    # ── Mitad izquierda: cancelar cita ────────────────────────────────────────
    with _t3_cancel_col:
        st.subheader("Cancelar cita de intervención")

        df_with_appointment = df[df["Fecha_Intervencion"].notna()].copy()
        if df_with_appointment.empty:
            st.info("No hay pacientes con cita de intervención asignada.")
        else:
            input_id = st.text_input("ID del paciente", placeholder="Escribe el ID del paciente...", key=f"cancel_id_{st.session_state['cancel_id_v']}")
            matches  = (
                df_with_appointment[df_with_appointment["ID_Paciente"].str.startswith(input_id)]
                if input_id else pd.DataFrame()
            )
            if input_id and matches.empty:
                st.warning("No se encontró ningún paciente con ese ID o no tiene cita asignada.")
            elif len(matches) > 1:
                st.info(f"{len(matches)} coincidencias. Escribe más caracteres para filtrar.")
                st.dataframe(
                    matches[["ID_Paciente", "Descripcion_Diagnostico_1", "Quirofano", "Fecha_Intervencion"]],
                    use_container_width=True, hide_index=True,
                )
            elif len(matches) == 1:
                selected_id = matches.iloc[0]["ID_Paciente"]
                patient     = df[df["ID_Paciente"] == selected_id].iloc[0]
                st.markdown(f"**Quirófano:** {patient['Quirofano']}  |  **Fecha:** {patient['Fecha_Intervencion']}  |  **Prioridad:** {patient['Prioridad']:.1f}%")

                _MOTIVOS = [
                    "Decisión del paciente",
                    "Complicación médica preoperatoria",
                    "No presentación",
                    "Falta de cama postoperatoria",
                    "Error administrativo",
                    "Otro",
                ]
                motivo = st.selectbox("Motivo de cancelación", options=_MOTIVOS, key="motivo_cancel")
                if motivo == "Otro":
                    motivo = st.text_input("Especifica el motivo", key="motivo_otro") or "Otro"

                if st.button("Cancelar cita", type="primary"):
                    mask = df["ID_Paciente"] == selected_id
                    save_gap(
                        str(patient["Fecha_Intervencion"]),
                        str(patient["Quirofano"]),
                        str(patient["Servicio"]),
                        float(patient["Duracion_Horas"] or 1.0),
                        str(patient["Codigo_Procedimiento"]),
                        selected_id,
                        motivo,
                    )
                    df.loc[mask, "Fecha_Intervencion"] = None
                    df.loc[mask, "Quirofano"]          = None
                    new_priority = calculate_priority(
                        int(patient["Edad"]), str(patient["Tipo_Cirugia"]),
                        str(patient["Fecha_Ingreso"]), None,
                    )
                    df.loc[mask, "Prioridad"] = new_priority
                    df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
                    load_data.clear()
                    st.session_state["cancel_id_v"] += 1
                    st.success(f"Cita cancelada. Prioridad: {patient['Prioridad']:.1f}% → {new_priority:.1f}%")
                    st.rerun(scope="app")

    # ── Mitad derecha: asignar cita manualmente ───────────────────────────────
    with _t3_assign_col:
        st.subheader("Asignar cita manualmente")

        _man_id = st.text_input("ID del paciente", placeholder="Escribe el ID...", key=f"man_id_{st.session_state['man_id_v']}")
        _man_matches = (
            df[df["ID_Paciente"].str.startswith(_man_id) & df["Fecha_Intervencion"].isna()]
            if _man_id else pd.DataFrame()
        )
        if _man_id and _man_matches.empty:
            st.warning("No se encontró ningún paciente sin cita con ese ID.")
        elif len(_man_matches) > 1:
            st.info(f"{len(_man_matches)} coincidencias. Escribe más caracteres para filtrar.")
            st.dataframe(
                _man_matches[["ID_Paciente", "Servicio", "Descripcion_Diagnostico_1", "Prioridad"]],
                use_container_width=True, hide_index=True,
            )
        elif len(_man_matches) == 1:
            _man_patient = _man_matches.iloc[0]
            _man_svc     = str(_man_patient["Servicio"])
            _man_dur     = float(_man_patient.get("Duracion_Horas") or 1.0)

            st.markdown(
                f"**Servicio:** {_man_svc}  |  **Prioridad:** {_man_patient['Prioridad']:.1f}%  |  "
                f"**Duración:** {_man_dur:.1f} h  |  **Ingreso:** {str(_man_patient['Fecha_Ingreso'])[:10]}"
            )

            _man_rooms    = ROOMS_BY_SERVICE.get(_man_svc, [])
            _man_ref_date = st.date_input("A partir del día", value=date.today(), key="man_date")

            _free_slots = find_free_slots(
                _man_rooms, _man_ref_date, _man_dur, df,
                closed_days=load_closed_days(),
                unavailable_specs=load_unavailable_specs(),
            )
            if not _man_rooms:
                st.warning("No hay quirófanos definidos para este servicio.")
            elif not _free_slots:
                st.warning("No se encontraron huecos libres en los próximos 365 días.")
            else:
                _slot_labels = [
                    f"{slot.strftime('%d/%m/%Y  %H:%M')}  —  {room}"
                    for slot, room in _free_slots
                ]
                _sel_label = st.radio(
                    "Próximos huecos disponibles",
                    options=_slot_labels,
                    key="man_slot_radio",
                )
                _chosen_slot, _chosen_room = _free_slots[_slot_labels.index(_sel_label)]

                if st.button("Confirmar cita", type="primary", key="btn_man_assign"):
                    _idx = _man_matches.index[0]
                    df.loc[_idx, "Fecha_Intervencion"] = _chosen_slot.strftime("%Y-%m-%d %H:%M")
                    df.loc[_idx, "Quirofano"]          = _chosen_room
                    df.loc[_idx, "Prioridad"]          = calculate_priority(
                        int(_man_patient["Edad"]),
                        str(_man_patient["Tipo_Cirugia"]),
                        str(_man_patient["Fecha_Ingreso"]),
                        _chosen_slot.strftime("%Y-%m-%d %H:%M"),
                    )
                    df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
                    load_data.clear()
                    st.session_state["man_id_v"] += 1
                    st.success(
                        f"Cita asignada: {_man_patient['ID_Paciente']} → "
                        f"{_chosen_room}  {_chosen_slot.strftime('%d/%m/%Y %H:%M')}"
                    )
                    st.rerun(scope="app")

    st.markdown("---")
    st.subheader("Huecos disponibles")

    gaps_df = load_gaps()
    if gaps_df.empty:
        st.info("No hay huecos disponibles actualmente.")
    else:
        for _, gap in gaps_df.iterrows():
            label = f"{gap['servicio']} · {gap['quirofano']} · {gap['fecha_intervencion']} · {gap['duracion_horas']}h"
            with st.expander(label):
                # ── Paciente que canceló ──────────────────────────────────────
                cancelled_id   = str(gap.get("id_paciente_cancelado", ""))
                cancelled_rows = df[df["ID_Paciente"] == cancelled_id]
                st.markdown("**Paciente que liberó el hueco**")
                if not cancelled_rows.empty:
                    cp = cancelled_rows.iloc[0]
                    ci1, ci2, ci3, ci4 = st.columns([2, 1, 1, 2])
                    ci1.markdown(f"**ID:** {cancelled_id}")
                    ci2.markdown(f"**Edad:** {int(cp['Edad'])} años")
                    ci3.markdown(f"**Prioridad:** {float(cp['Prioridad']):.1f}%")
                    ci4.markdown(f"**Motivo:** {gap.get('motivo_cancelacion', '—')}")
                    st.caption(
                        f"{cp.get('Codigo_Procedimiento','—')} — "
                        f"{str(cp.get('Descripcion_Procedimiento',''))[:90]}"
                    )
                    if st.button("Ver ficha completa", key=f"show_cancelled_{gap['id_gap']}"):
                        _show_patient_dialog(cp)
                else:
                    st.caption(f"ID: {cancelled_id}  ·  Motivo: {gap.get('motivo_cancelacion', '—')}")

                st.markdown("---")

                # ── Candidatos con carga bajo demanda ────────────────────────
                _PAGE    = 3
                _off_key = f"cand_offset_{gap['id_gap']}"
                if _off_key not in st.session_state:
                    st.session_state[_off_key] = 0
                _offset = st.session_state[_off_key]

                # find_candidates devuelve PAGE+1 filas: la extra indica si hay más
                candidates = find_candidates(df, gap.to_dict(), n=_PAGE, offset=_offset)
                has_more   = len(candidates) > _PAGE
                page_cands = candidates.head(_PAGE)

                if page_cands.empty:
                    st.warning("No hay candidatos disponibles para este hueco.")
                    if st.button("Descartar hueco", key=f"disc_{gap['id_gap']}"):
                        remove_gap(str(gap["id_gap"]))
                        st.rerun(scope="app")
                else:
                    sel_key = f"sel_{gap['id_gap']}"
                    if sel_key not in st.session_state:
                        st.session_state[sel_key] = page_cands["ID_Paciente"].iloc[0]
                    selected_candidate = st.session_state[sel_key]

                    hdr = st.columns([3, 4, 1, 1, 1, 1])
                    hdr[0].markdown("**ID Paciente**")
                    hdr[1].markdown("**Procedimiento**")
                    hdr[2].markdown("**Prioridad**")
                    hdr[3].markdown("**Similitud**")
                    hdr[4].markdown("**Puntuación**")
                    hdr[5].markdown("**Selección**")

                    for _, cand in page_cands.iterrows():
                        pid      = cand["ID_Paciente"]
                        is_sel   = pid == selected_candidate
                        row_cols = st.columns([3, 4, 1, 1, 1, 1])
                        with row_cols[0]:
                            if st.button(pid, key=f"pid_{gap['id_gap']}_{pid}", use_container_width=True):
                                _show_patient_dialog(df[df["ID_Paciente"] == pid].iloc[0])
                        row_cols[1].write(str(cand["Descripcion_Procedimiento"])[:65])
                        row_cols[2].write(f"{cand['Prioridad']:.1f}%")
                        row_cols[3].write(f"{cand['Similitud']:.2f}")
                        row_cols[4].write(f"{cand['Puntuacion']:.3f}")
                        with row_cols[5]:
                            if is_sel:
                                st.success("Elegido")
                            elif st.button("Elegir", key=f"elegir_{gap['id_gap']}_{pid}", use_container_width=True):
                                st.session_state[sel_key] = pid
                                st.rerun()

                    _btn_cols = st.columns([2, 2, 6])
                    with _btn_cols[0]:
                        if has_more:
                            if st.button("Otros candidatos", key=f"more_cand_{gap['id_gap']}"):
                                st.session_state[_off_key] = _offset + _PAGE
                                st.rerun()
                    with _btn_cols[1]:
                        if _offset > 0:
                            if st.button("Candidatos originales", key=f"reset_cand_{gap['id_gap']}"):
                                st.session_state[_off_key] = 0
                                st.rerun()

                    st.markdown("")
                    btn_a, btn_b = st.columns([1, 4])
                    with btn_a:
                        if st.button("Asignar", type="primary", key=f"assign_{gap['id_gap']}"):
                            idx = df[df["ID_Paciente"] == selected_candidate].index[0]
                            df.loc[idx, "Fecha_Intervencion"] = gap["fecha_intervencion"]
                            df.loc[idx, "Quirofano"]          = gap["quirofano"]
                            df.loc[idx, "Prioridad"]          = calculate_priority(
                                int(df.loc[idx, "Edad"]),
                                str(df.loc[idx, "Tipo_Cirugia"]),
                                str(df.loc[idx, "Fecha_Ingreso"]),
                                str(gap["fecha_intervencion"]),
                            )
                            df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
                            remove_gap(str(gap["id_gap"]))
                            load_data.clear()
                            st.success(f"Paciente {selected_candidate[:8]}… asignado al hueco.")
                            st.rerun(scope="app")
                    with btn_b:
                        if st.button("Descartar hueco", key=f"disc_{gap['id_gap']}"):
                            remove_gap(str(gap["id_gap"]))
                            st.rerun(scope="app")

    st.markdown("---")
    st.subheader("Tabla de pacientes")

    _search_id = st.text_input(
        "Buscar por ID de paciente", placeholder="Escribe parte del ID…", key="table_search_id"
    )

    table_cols = [
        "ID_Paciente", "Edad", "Sexo", "Servicio", "Prioridad",
        "Fecha_Ingreso", "Fecha_Intervencion", "Quirofano", "Duracion_Horas",
        "Codigo_Diagnostico_1", "Descripcion_Diagnostico_1",
        "Codigo_Procedimiento", "Descripcion_Procedimiento",
        "Comorbilidades",
    ]
    _editable_cols = {"Fecha_Ingreso", "Duracion_Horas", "Comorbilidades"}
    _disabled_cols = [c for c in table_cols if c not in _editable_cols]

    _df_table = df[df["ID_Paciente"].str.contains(_search_id, case=False, na=False)] if _search_id else df
    table = _df_table[table_cols].reset_index(drop=True).copy()
    table["Fecha_Ingreso"]      = pd.to_datetime(table["Fecha_Ingreso"],      errors="coerce").dt.date
    table["Fecha_Intervencion"] = pd.to_datetime(table["Fecha_Intervencion"], errors="coerce")
    col_config = {
        "Prioridad": st.column_config.ProgressColumn(
            "Prioridad",
            help="Score 0–100: espera (40 %) + edad (30 %) + invasividad cirugía (30 %)",
            min_value=0, max_value=100, format="%.1f%%",
        ),
        "Fecha_Ingreso":     st.column_config.DateColumn("Fecha ingreso",      format="DD/MM/YYYY"),
        "Fecha_Intervencion": st.column_config.DatetimeColumn("Fecha intervención", format="DD/MM/YYYY HH:mm"),
        "Duracion_Horas":    st.column_config.NumberColumn("Duración (h)", min_value=0.5, step=0.5, format="%.1f h"),
        "Comorbilidades":    st.column_config.TextColumn("Comorbilidades"),
    }

    if st.toggle("Habilitar edición", key="toggle_edit_table"):
        edited = st.data_editor(
            table, column_config=col_config,
            disabled=_disabled_cols,
            use_container_width=True, height=400,
        )
        if st.button("Guardar cambios", key="btn_save_table"):
            df_updated = df.set_index("ID_Paciente").copy()
            edited_idx = edited.set_index("ID_Paciente")
            for col in _editable_cols:
                df_updated[col] = df_updated[col].where(
                    ~df_updated.index.isin(edited_idx.index),
                    edited_idx[col],
                )
            df_updated.reset_index().to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
            load_data.clear()
            st.success("Cambios guardados.")
            st.rerun(scope="app")
    else:
        st.dataframe(table, column_config=col_config, use_container_width=True, height=400)

with tab3:
    _tab3_fn()

# ── TAB 4: PLANIFICACIÓN ──────────────────────────────────────────────────────
@st.fragment
def _tab4_fn():
    plan_col, delete_col = st.columns(2)

    # ── Mitad izquierda: planificar ───────────────────────────────────────────
    with plan_col:
        st.subheader("Planificar intervenciones")

        plan_service = st.selectbox(
            "Servicio", options=sorted(df["Servicio"].dropna().unique()), key="plan_svc",
        )
        pd1, pd2 = st.columns(2)
        with pd1:
            plan_start = st.date_input("Desde", value=date.today(), key="plan_start")
        with pd2:
            plan_end = st.date_input("Hasta", value=date.today() + timedelta(weeks=2), key="plan_end")

        svc_mask = df["Servicio"] == plan_service
        n_total  = int(svc_mask.sum())
        n_sched  = int(df.loc[svc_mask, "Fecha_Intervencion"].notna().sum())
        st.caption(
            f"**{plan_service}** — {n_total} pacientes · "
            f"{n_sched} con cita · {n_total - n_sched} en espera"
        )

        service_rooms   = ROOMS_BY_SERVICE.get(plan_service, [])
        svc_specialists = specialists_for_service(plan_service)
        spec_name_to_id = {s["name"]: s["id"] for s in svc_specialists}
        spec_id_to_name = {v: k for k, v in spec_name_to_id.items()}
        spec_options    = list(spec_name_to_id)
        _time_options   = [f"{h:02d}:{m:02d}" for h in range(8, 22) for m in (0, 30)] + ["22:00"]

        with st.expander("Quirófanos no disponibles"):
            # Cargar filas del CSV para los quirófanos de este servicio
            _cd_csv = load_closed_days_df()
            _cd_svc = _cd_csv[_cd_csv["quirofano"].isin(service_rooms)].copy()
            _cd_svc["fecha"] = pd.to_datetime(_cd_svc["fecha"], errors="coerce").dt.date
            _cd_init = pd.DataFrame({
                "Quirófano": _cd_svc["quirofano"].tolist(),
                "Fecha":     _cd_svc["fecha"].tolist(),
            }) if not _cd_svc.empty else pd.DataFrame({"Quirófano": pd.Series(dtype=str), "Fecha": pd.Series(dtype="object")})

            closed_df = st.data_editor(
                _cd_init,
                column_config={
                    "Quirófano": st.column_config.SelectboxColumn("Quirófano", options=service_rooms, required=True),
                    "Fecha":     st.column_config.DateColumn("Fecha", format="DD/MM/YYYY", required=True),
                },
                num_rows="dynamic", use_container_width=True, hide_index=True,
                key=f"closed_days_editor_{plan_service}",
            )

        with st.expander("Especialistas no disponibles"):
            # Cargar filas del CSV para los especialistas de este servicio
            _svc_spec_ids = list(spec_name_to_id.values())
            _us_csv = load_unavailable_specs_df()
            _us_svc = _us_csv[_us_csv["especialista_id"].isin(_svc_spec_ids)].copy()
            _us_init = pd.DataFrame({
                "Especialista": _us_svc["especialista_id"].map(spec_id_to_name).tolist(),
                "Fecha":        pd.to_datetime(_us_svc["fecha"], errors="coerce").dt.date.tolist(),
                "Hora inicio":  _us_svc["hora_inicio"].tolist(),
                "Hora fin":     _us_svc["hora_fin"].tolist(),
            }) if not _us_svc.empty else pd.DataFrame({
                "Especialista": pd.Series(dtype=str),
                "Fecha":        pd.Series(dtype="object"),
                "Hora inicio":  pd.Series(dtype=str),
                "Hora fin":     pd.Series(dtype=str),
            })

            unavail_spec_df = st.data_editor(
                _us_init,
                column_config={
                    "Especialista": st.column_config.SelectboxColumn("Especialista", options=spec_options, required=True),
                    "Fecha":        st.column_config.DateColumn("Fecha", format="DD/MM/YYYY", required=True),
                    "Hora inicio":  st.column_config.SelectboxColumn("Hora inicio", options=_time_options),
                    "Hora fin":     st.column_config.SelectboxColumn("Hora fin",    options=_time_options),
                },
                num_rows="dynamic", use_container_width=True, hide_index=True,
                key=f"unavail_spec_editor_{plan_service}",
            )
            if svc_specialists:
                def _spec_rooms(spec_id: str) -> list[str]:
                    return [r for r, specs in SPECIALISTS_BY_ROOM.items() if any(s["id"] == spec_id for s in specs)]
                turno_label = {8: "mañana", 15: "tarde"}
                spec_info = "  \n".join(
                    f"**{s['name']}** — {', '.join(_spec_rooms(s['id']))} ({turno_label.get(s['start_hour'], '')})"
                    for s in svc_specialists
                )
                st.caption(spec_info)

        if st.button("Planificar", type="primary", key="btn_planificar"):
            if plan_start > plan_end:
                st.error("La fecha de inicio debe ser anterior a la fecha de fin.")
            else:
                # Guardar restricciones del editor al CSV
                _cd_rows = [
                    {"quirofano": str(r["Quirófano"]), "fecha": pd.to_datetime(r["Fecha"]).date().isoformat()}
                    for _, r in closed_df.dropna(subset=["Quirófano", "Fecha"]).iterrows()
                ]
                save_closed_days_for_rooms(service_rooms, _cd_rows)

                spec_data_by_id = {s["id"]: s for s in svc_specialists}
                def _hm(val, default_h: int) -> tuple[int, int]:
                    if pd.isna(val):
                        return default_h, 0
                    t = datetime.strptime(str(val), "%H:%M")
                    return t.hour, t.minute

                _us_rows = []
                for _, row in unavail_spec_df.dropna(subset=["Especialista", "Fecha"]).iterrows():
                    spec_id   = spec_name_to_id.get(str(row["Especialista"]))
                    spec_data = spec_data_by_id.get(spec_id) if spec_id else None
                    if not spec_data:
                        continue
                    _us_rows.append({
                        "especialista_id":     spec_id,
                        "especialista_nombre": str(row["Especialista"]),
                        "fecha":               pd.to_datetime(row["Fecha"]).date().isoformat(),
                        "hora_inicio":         str(row.get("Hora inicio", f"{spec_data['hora_inicio']:02d}:00")),
                        "hora_fin":            str(row.get("Hora fin",    f"{spec_data['hora_fin']:02d}:00")),
                    })
                save_unavailable_specs_for_ids(_svc_spec_ids, _us_rows)

                # Reconstruir dicts para el planificador desde los datos del editor
                closed_days: dict[str, list[date]] = {}
                for r in _cd_rows:
                    closed_days.setdefault(r["quirofano"], []).append(date.fromisoformat(r["fecha"]))

                unavailable_specs: dict[str, list[tuple[datetime, datetime]]] = {}
                for _, row in unavail_spec_df.dropna(subset=["Especialista", "Fecha"]).iterrows():
                    spec_id   = spec_name_to_id.get(str(row["Especialista"]))
                    spec_data = spec_data_by_id.get(spec_id) if spec_id else None
                    if not spec_data:
                        continue
                    d            = pd.to_datetime(row["Fecha"]).date()
                    ini_h, ini_m = _hm(row["Hora inicio"], spec_data["hora_inicio"])
                    fin_h, fin_m = _hm(row["Hora fin"],    spec_data["hora_fin"])
                    unavailable_specs.setdefault(spec_id, []).append((
                        datetime(d.year, d.month, d.day, ini_h, ini_m),
                        datetime(d.year, d.month, d.day, fin_h, fin_m),
                    ))

                from planificador import service_planning
                # Cargar quirófano de tarde asignado a este servicio (si existe)
                _ta = load_tarde_assignment()
                _tarde_for_service = next(
                    (room for room, svc in _ta.items() if svc == plan_service), None
                )
                df_new, n_new = service_planning(
                    df, plan_service, plan_end, plan_start,
                    closed_days or None, unavailable_specs or None,
                    tarde_room=_tarde_for_service,
                )
                df_new.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
                load_data.clear()
                st.success(
                    f"{n_new} pacientes asignados en **{plan_service}** "
                    f"({plan_start.strftime('%d/%m/%Y')} – {plan_end.strftime('%d/%m/%Y')})."
                )
                st.rerun(scope="app")

    # ── Mitad derecha: borrar ─────────────────────────────────────────────────
    with delete_col:
        st.subheader("Borrar planificación")

        delete_service = st.selectbox(
            "Servicio", options=sorted(df["Servicio"].dropna().unique()), key="delete_svc",
        )
        dd1, dd2 = st.columns(2)
        with dd1:
            delete_start = st.date_input("Desde", value=date.today(), key="delete_start")
        with dd2:
            delete_end = st.date_input("Hasta", value=date.today() + timedelta(weeks=2), key="delete_end")

        if st.button("Borrar planificación", key="btn_delete_plan"):
            if delete_start > delete_end:
                st.error("La fecha de inicio debe ser anterior a la fecha de fin.")
            else:
                st.session_state["confirm_delete_plan"] = True

        if st.session_state.get("confirm_delete_plan"):
            st.warning(
                f"Vas a eliminar todas las citas de **{delete_service}** "
                f"entre el **{delete_start.strftime('%d/%m/%Y')}** y el **{delete_end.strftime('%d/%m/%Y')}**. "
                "Esta acción no se puede deshacer."
            )
            c_ok, c_cancel, _ = st.columns([1, 1, 3])
            with c_ok:
                if st.button("Confirmar borrado", type="primary", key="confirm_delete_btn"):
                    _slots_del = pd.to_datetime(df["Fecha_Intervencion"], errors="coerce")
                    _del_mask  = (
                        (df["Servicio"] == delete_service)
                        & df["Fecha_Intervencion"].notna()
                        & (_slots_del >= pd.Timestamp(delete_start))
                        & (_slots_del <= pd.Timestamp(delete_end))
                    )
                    _n_del = int(_del_mask.sum())
                    df.loc[_del_mask, ["Fecha_Intervencion", "Quirofano"]] = None
                    df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
                    load_data.clear()
                    st.session_state.pop("confirm_delete_plan", None)
                    st.success(f"{_n_del} cita(s) eliminadas de **{delete_service}**.")
                    st.rerun(scope="app")
            with c_cancel:
                if st.button("Cancelar", key="cancel_delete_btn"):
                    st.session_state.pop("confirm_delete_plan", None)
                    st.rerun()

    st.markdown("---")
    st.subheader("Quirófanos de tarde")
    st.caption(
        "Asigna cada quirófano de tarde (TARDE-Q1, TARDE-Q2) al servicio que más impacto tendrá. "
        "La asignación se guarda y se usa al planificar intervenciones."
    )

    # Calcular impacto solo al inicio o cuando el usuario lo solicita
    if "tarde_impact" not in st.session_state:
        with st.spinner("Calculando impacto de quirófanos de tarde..."):
            st.session_state["tarde_impact"] = _compute_tarde_impact()
    if st.button("Recalcular impacto", key="btn_recalc_impact"):
        with st.spinner("Recalculando..."):
            st.session_state["tarde_impact"] = _compute_tarde_impact()
    _impact = st.session_state["tarde_impact"]

    # Cargar asignación persistida
    _tarde_assignment = load_tarde_assignment()

    _ta_col1, _ta_col2 = st.columns(2)
    _new_assignment: dict[str, str] = {}
    for _i, _tarde_room_name in enumerate(TARDE_ROOMS):
        _col = _ta_col1 if _i == 0 else _ta_col2
        with _col:
            st.markdown(f"**{_tarde_room_name}**")
            # Mostrar tabla de impacto como referencia
            st.dataframe(
                _impact[["Servicio", "Sin cita", "Asignados (M)", "Dur. media (h)", "Impacto cap.", "Espera sim. (d)"]],
                use_container_width=True,
                hide_index=True,
                height=220,
            )
            # Servicio actualmente asignado (si existe)
            _current_svc = _tarde_assignment.get(_tarde_room_name)
            _svc_options  = ["(ninguno)"] + list(_impact["Servicio"])
            _default_idx  = _svc_options.index(_current_svc) if _current_svc in _svc_options else 0
            _selected_svc = st.selectbox(
                f"Asignar {_tarde_room_name} a",
                options=_svc_options,
                index=_default_idx,
                key=f"tarde_assign_{_tarde_room_name}",
            )
            _new_assignment[_tarde_room_name] = _selected_svc if _selected_svc != "(ninguno)" else ""

    if st.button("Guardar asignación de quirófanos de tarde", key="btn_save_tarde"):
        _clean = {k: v for k, v in _new_assignment.items() if v}
        # Validar que cada quirófano se asigne a un servicio distinto
        _assigned_svcs = list(_clean.values())
        if len(_assigned_svcs) != len(set(_assigned_svcs)):
            st.error("Cada quirófano de tarde debe asignarse a un servicio diferente.")
        else:
            save_tarde_assignment(_clean)
            st.success("Asignación guardada.")
            st.rerun(scope="app")

    st.markdown("---")
    st.subheader("Exportar planificación en PDF")

    ex1, ex2, ex3 = st.columns([3, 2, 2])
    with ex1:
        export_service = st.selectbox(
            "Servicio", options=sorted(df["Servicio"].dropna().unique()), key="export_svc",
        )
    with ex2:
        export_start = st.date_input("Desde", value=date.today(), key="export_start")
    with ex3:
        export_end = st.date_input("Hasta", value=date.today() + timedelta(weeks=4), key="export_end")

    if st.button("Generar PDF", type="primary", key="btn_pdf"):
        if export_start > export_end:
            st.error("La fecha de inicio debe ser anterior a la fecha de fin.")
        else:
            from pdf_export import build_pdf
            st.session_state["pdf_bytes"]    = build_pdf(df, export_service, export_start, export_end)
            st.session_state["pdf_filename"] = f"planificacion_{export_service.replace(' ', '_')}_{export_start}.pdf"

    if st.session_state.get("pdf_bytes"):
        st.download_button(
            label="Descargar PDF",
            data=st.session_state["pdf_bytes"],
            file_name=st.session_state["pdf_filename"],
            mime="application/pdf",
            key="download_pdf",
        )

    st.markdown("---")
    st.subheader("Calendario de quirófanos")

    cc1, cc2 = st.columns(2)
    with cc1:
        cal_service = st.selectbox(
            "Servicio", options=sorted(df["Servicio"].dropna().unique()), key="cal_service",
        )
    cal_rooms = ROOMS_BY_SERVICE.get(cal_service, [])
    with cc2:
        cal_room = st.selectbox("Quirófano", options=cal_rooms, key="cal_room") if cal_rooms else None

    if not cal_rooms:
        st.info("No hay quirófanos definidos para este servicio.")
    else:
        ROOM_COLORS = ["#3788d8", "#e74c3c", "#2ecc71", "#f39c12", "#9b59b6", "#1abc9c", "#e67e22", "#34495e"]
        room_color  = {r: ROOM_COLORS[i % len(ROOM_COLORS)] for i, r in enumerate(cal_rooms)}

        df_events = df[df["Quirofano"].notna() & df["Fecha_Intervencion"].notna()].copy()
        df_events = df_events[df_events["Servicio"] == cal_service]
        df_events = df_events[df_events["Quirofano"] == cal_room]

        events = []
        for _, row in df_events.iterrows():
            start_dt = pd.to_datetime(row["Fecha_Intervencion"])
            end_dt   = start_dt + pd.Timedelta(hours=float(row.get("Duracion_Horas", 1.0) or 1.0))
            events.append({
                "title": f"{row['Quirofano']} · {row['ID_Paciente'][:8]}",
                "start": start_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                "end":   end_dt.strftime("%Y-%m-%dT%H:%M:%S"),
                "color": room_color.get(row["Quirofano"], "#3788d8"),
                "extendedProps": {"servicio": row["Servicio"], "diagnostico": row["Descripcion_Diagnostico_1"]},
            })

        st_calendar(events=events, options={
            "initialView": "timeGridWeek",
            "headerToolbar": {"left": "prev,next today", "center": "title", "right": "dayGridMonth,timeGridWeek,timeGridDay"},
            "slotMinTime": "08:00:00", "slotMaxTime": "22:00:00",
            "locale": "es", "height": 500,
        })

with tab4:
    _tab4_fn()
