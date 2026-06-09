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
from quirofanos_pm import PM_ROOMS, load_pm_assignment, save_pm_assignment
from planificador import service_planning, find_free_slots, compute_pm_impact
from planning_log import save_planning, get_reference_date
from streamlit_extras.metric_cards import style_metric_cards
from restricciones import (
    load_closed_days_df, save_closed_days_for_rooms, load_closed_days,
    load_unavailable_specs_df, save_unavailable_specs_for_ids, load_unavailable_specs,
)
import streamlit.components.v1 as components

st.set_page_config(page_title="Dashboard Lista de Espera", layout="wide")

components.html("""
<script>
const doc = window.parent.document;
let _timer;
function styleCards() {
    clearTimeout(_timer);
    _timer = setTimeout(() => {
        doc.querySelectorAll('[data-testid="stVerticalBlock"]:not([data-card-styled])').forEach(el => {
            const b = window.parent.getComputedStyle(el).borderTopWidth;
            if (b && b !== '0px') {
                el.style.setProperty('background-color', '#c8ddf5', 'important');
                el.setAttribute('data-card-styled', '1');
            }
        });
    }, 60);
}
styleCards();
new MutationObserver(styleCards).observe(doc.body, {childList: true, subtree: true});
</script>
""", height=0, scrolling=False)


@st.dialog("Información del paciente", width="large")
def _show_patient_dialog(patient: pd.Series) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric("Edad",      f"{int(patient['Edad'])} años")
    c2.metric("Sexo",      str(patient.get("Sexo", "—")))
    c3.metric("Prioridad", f"{float(patient['Prioridad']):.1f}%")

    st.divider()
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**ID**")
        st.write(str(patient["ID_Paciente"]))
        st.markdown("**Servicio**")
        st.write(patient.get("Servicio", "—"))
        st.markdown("**Tipo de cirugía**")
        st.write(patient.get("Tipo_Cirugia", "—"))
        st.markdown("**Fecha de ingreso**")
        st.write(str(patient.get("Fecha_Ingreso", "—"))[:10])
    with col_b:
        st.markdown("**Diagnóstico**")
        st.write(f"{patient.get('Codigo_Diagnostico','—')} — {patient.get('Descripcion_Diagnostico','')}")
        st.markdown("**Procedimiento**")
        st.write(f"{patient.get('Codigo_Procedimiento','—')} — {patient.get('Descripcion_Procedimiento','')}")

    if pd.notna(patient.get("Comorbilidades")) and str(patient.get("Comorbilidades", "")).strip():
        st.divider()
        st.markdown("**Comorbilidades**")
        st.write(patient["Comorbilidades"])

CSV_PATH = str(Path(__file__).parent.parent / "datos_generados" / "lista_espera_quirurgica.csv")

@st.cache_data
def load_data(mtime: float):
    return pd.read_csv(CSV_PATH)


df = load_data(os.path.getmtime(CSV_PATH))

# Precalcular Dias_Espera sobre el dataset completo (necesario para el filtro de tramo)
_today = date.today()
_ingreso_dt = pd.to_datetime(df["Fecha_Ingreso"])
_interv_dt  = pd.to_datetime(df["Fecha_Intervencion"], errors="coerce")
_sched_all  = df["Fecha_Intervencion"].notna()
df["Dias_Espera"] = (pd.Timestamp(_today) - _ingreso_dt).dt.days
df.loc[_sched_all, "Dias_Espera"] = (_interv_dt[_sched_all] - _ingreso_dt[_sched_all]).dt.days

st.title("Dashboard")

with open(Path(__file__).parent / "style.css") as _f:
    st.markdown(f"<style>{_f.read()}</style>", unsafe_allow_html=True)




_TRAMO_BINS = {
    "< 30 d":   (0,   30),
    "30–60 d":  (30,  60),
    "60–90 d":  (60,  90),
    "90–180 d": (90,  180),
    "> 180 d":  (180, 99_999),
}

# KPIs generales 
_sched_g     = df["Fecha_Intervencion"].notna()
_n_espera_g  = int((~_sched_g).sum())
_dem_media_g = df["Dias_Espera"].mean()
_dem_max_g   = int(df["Dias_Espera"].max())
_edad_esp_g  = df.loc[~_sched_g, "Edad"].mean() if _n_espera_g > 0 else None
_hp_g        = df["Prioridad"] >= 70
_indice_g    = int((_hp_g & ~_sched_g).sum())
_df_g        = df.copy()

tab1, tab2, tab3, tab4 = st.tabs(["Resumen", "Análisis", "Pacientes", "Planificación"])

# TAB 1: RESUMEN 
with tab1:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Pacientes",      len(df))
    col2.metric("Edad media",     f"{df['Edad'].mean():.1f}")
    col3.metric("Servicios",      df["Servicio"].nunique())
    col4.metric("Prioridad media", f"{df['Prioridad'].mean():.1f}%")

    st.divider()

    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Sin cita",            _n_espera_g)
    k2.metric("Demora media",        f"{_dem_media_g:.0f} d")
    k3.metric("Demora máxima",       f"{_dem_max_g} d")
    k4.metric("Edad media (espera)", f"{_edad_esp_g:.1f}" if _edad_esp_g is not None else "—")
    k5.metric("Alta prio. sin cita",    str(_indice_g))
    style_metric_cards(background_color="#ffffff", border_left_color="#2563eb", border_color="#e2e8f0", box_shadow=True)

    st.divider()

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
        fig.update_layout(coloraxis_showscale=False, margin={"t": 40, "b": 10, "l": 220, "r": 20}, height=380)
        st.plotly_chart(fig, use_container_width=True)

    with g2:
        count = df["Servicio"].value_counts().reset_index()
        count.columns = ["Servicio", "Pacientes"]
        fig = px.bar(count, x="Servicio", y="Pacientes", title="Pacientes por servicio",
                     color="Pacientes",
                     color_continuous_scale=[(0, "#5b9bd5"), (1, "#1e3a8a")],
                     range_color=[0, count["Pacientes"].max()])
        fig.update_layout(showlegend=False, coloraxis_showscale=False, xaxis_tickangle=-35, height=380, margin={"t": 40, "b": 60, "l": 20, "r": 20})
        st.plotly_chart(fig, use_container_width=True)

    with g3:
        fig = px.histogram(df, x="Prioridad", nbins=20,
                           title="Distribución de prioridad",
                           labels={"Prioridad": "Prioridad (%)"},
                           color_discrete_sequence=["#e74c3c"])
        fig.update_layout(bargap=0.05, xaxis_range=[0, 100], height=380, margin={"t": 40, "b": 40, "l": 20, "r": 20})
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    r1, r2 = st.columns(2)

    with r1:
        df_occ_g = df[df["Fecha_Intervencion"].notna()].copy()
        if not df_occ_g.empty:
            df_occ_g["interv_dt"] = pd.to_datetime(df_occ_g["Fecha_Intervencion"], format="mixed", errors="coerce")
            occ_rows = []
            for svc, grp in df_occ_g.groupby("Servicio"):
                n_rooms = len(ROOMS_BY_SERVICE.get(svc, []))
                if n_rooms == 0:
                    continue
                surgery_days = grp["interv_dt"].dt.date.nunique()
                avail_h      = n_rooms * surgery_days * 8
                used_h       = grp["Duracion_Horas"].fillna(0).sum()
                occ_rows.append({
                    "Servicio":      svc,
                    "Ocupación (%)": round(min(used_h / avail_h * 100, 100), 1) if avail_h > 0 else 0,
                    "Horas usadas":  round(used_h, 1),
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
            fig_occ.update_layout(coloraxis_showscale=False, margin={"t": 40, "b": 10, "l": 220, "r": 60}, xaxis_range=[0, 110], height=380)
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
        fig_ratio.update_layout(xaxis_tickangle=-35, legend_title_text="", height=380, margin={"t": 40, "b": 60, "l": 20, "r": 20})
        st.plotly_chart(fig_ratio, use_container_width=True)

    st.divider()

    fig_box = px.box(
        df, x="Servicio", y="Dias_Espera",
        title="Distribución de días de espera por servicio",
        labels={"Dias_Espera": "Días de espera", "Servicio": ""},
        color="Servicio",
        points="outliers",
    )
    fig_box.update_layout(showlegend=False, xaxis_tickangle=-35, height=360, margin={"t": 40, "b": 60, "l": 20, "r": 20})
    st.plotly_chart(fig_box, use_container_width=True)

# TAB 2: ANÁLISIS 
@st.fragment
def _tab2_fn():
    # Selector de servicio + KPIs (no dependen de los demás filtros)
    _svc_col, _ = st.columns([2, 6])
    with _svc_col:
        selected_service = st.selectbox("Servicio", options=sorted(df["Servicio"].dropna().unique()), key="ana_svc")

    svc_all     = df[df["Servicio"] == selected_service]
    svc_sched   = svc_all["Fecha_Intervencion"].notna()
    svc_n       = len(svc_all)
    svc_pct     = svc_sched.sum() / svc_n * 100 if svc_n > 0 else 0
    svc_dem     = svc_all["Dias_Espera"].mean()
    svc_dem_max = int(svc_all["Dias_Espera"].max())
    svc_prio    = svc_all["Prioridad"].mean()
    svc_hp      = svc_all["Prioridad"] >= 70
    svc_idx     = int((svc_hp & svc_all["Fecha_Intervencion"].isna()).sum())
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Pacientes en servicio", svc_n)
    k2.metric("Con cita asignada",     f"{svc_pct:.0f}%")
    k3.metric("Demora media",          f"{svc_dem:.0f} d")
    k4.metric("Demora máxima",         f"{svc_dem_max} d")
    k5.metric("Prioridad media",       f"{svc_prio:.1f}%")
    k6.metric("Alta prio. sin cita",   str(svc_idx))

    st.divider()

    # Filtros adicionales para los gráficos
    f1, f2, f3, _ = st.columns([3, 2, 2, 1])
    with f1:
        prio_min, prio_max = st.slider("Rango de prioridad (%)", 0, 100, (0, 100), step=1, key="ana_prio")
    with f2:
        estado_cita = st.selectbox("Estado de cita", options=["Todos", "Sin cita", "Con cita"], key="ana_estado")
    with f3:
        tramo_sel = st.selectbox("Tramo de espera", options=["Todos"] + list(_TRAMO_BINS), key="ana_tramo")

    # Computar máscaras y dataset filtrado
    svc_mask = df["Servicio"] == selected_service
    prio_mask = df["Prioridad"].between(prio_min, prio_max)
    estado_mask = (
        df["Fecha_Intervencion"].isna()  if estado_cita == "Sin cita"  else
        df["Fecha_Intervencion"].notna() if estado_cita == "Con cita"  else
        pd.Series(True, index=df.index)
    )
    if tramo_sel != "Todos":
        lo, hi     = _TRAMO_BINS[tramo_sel]
        tramo_mask = df["Dias_Espera"].between(lo, hi - 1)
    else:
        tramo_mask = pd.Series(True, index=df.index)
    df_filtered = df[svc_mask & prio_mask & estado_mask & tramo_mask]
    df_view = df_filtered.copy() if not df_filtered.empty else None

    st.divider()

    # Fila 1: scatter · tramos · horas semanales 
    r1c1, r1c2, r1c3 = st.columns(3)

    with r1c1:
        scatter_threshold = st.session_state.get("scatter_threshold", 70)
        if df_view is not None:
            fig_scatter = px.scatter(
                df_view, x="Dias_Espera", y="Prioridad",
                title="Prioridad vs. días de espera",
                labels={"Dias_Espera": "Días en espera", "Prioridad": "Prioridad (%)"},
                hover_data=["ID_Paciente", "Descripcion_Diagnostico"],
                opacity=0.6,
                color_discrete_sequence=["#3788d8"],
            )
            fig_scatter.add_hline(
                y=scatter_threshold, line_dash="dash", line_color="red",
                annotation_text=f"Alta prioridad ({scatter_threshold})", annotation_position="top right",
            )
            fig_scatter.update_layout(height=340, margin={"t": 40, "b": 40, "l": 40, "r": 20})
            st.plotly_chart(fig_scatter, use_container_width=True)
        else:
            st.info("Sin datos para este filtro.")
        st.number_input(
            "Umbral alta prioridad (%)", min_value=0, max_value=100, value=scatter_threshold, step=5, key="scatter_threshold",
        )

    with r1c2:
        if df_view is not None:
            bins   = [0, 30, 60, 90, 180, 10_000]
            labels = ["< 30 d", "30–60 d", "60–90 d", "90–180 d", "> 180 d"]
            tramos = df_view.copy()
            tramos["Tramo"] = pd.cut(tramos["Dias_Espera"], bins=bins, labels=labels, right=False)
            tramo_counts = tramos["Tramo"].value_counts().reindex(labels).fillna(0).reset_index()
            tramo_counts.columns = ["Tramo", "Pacientes"]
            tramo_counts["Pct"] = (tramo_counts["Pacientes"] / tramo_counts["Pacientes"].sum() * 100).round(1)
            fig_tramos = px.bar(
                tramo_counts, x="Tramo", y="Pacientes",
                title="Pacientes por tramo de espera",
                text=tramo_counts["Pct"].apply(lambda v: f"{v:.1f}%"),
                color="Tramo",
                color_discrete_sequence=px.colors.sequential.Greens[2:],
            )
            fig_tramos.update_traces(textposition="outside")
            fig_tramos.update_layout(showlegend=False, height=340, margin={"t": 40, "b": 40, "l": 20, "r": 20})
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
            fig_wk.update_layout(height=340, margin={"t": 40, "b": 40, "l": 40, "r": 20})
            st.plotly_chart(fig_wk, use_container_width=True)
        else:
            st.info("Sin intervenciones planificadas.")

    st.divider()

    # Fila 2: edad · tipo cirugía · alta prioridad sin cita 
    r2c1, r2c2, r2c3 = st.columns(3)

    with r2c1:
        if df_view is not None:
            fig_age = px.histogram(
                df_view, x="Edad", nbins=20,
                title="Distribución de edad",
                labels={"Edad": "Edad (años)", "count": "Pacientes"},
                opacity=0.8,
                color_discrete_sequence=["#3788d8"],
            )
            fig_age.update_layout(bargap=0.05, showlegend=False, height=340, margin={"t": 40, "b": 40, "l": 40, "r": 20})
            st.plotly_chart(fig_age, use_container_width=True)
        else:
            st.info("Sin datos para este filtro.")

    with r2c2:
        if df_view is not None:
            tipo = df_view.copy()
            tipo["Estado"] = tipo["Fecha_Intervencion"].apply(
                lambda x: "Con cita" if pd.notna(x) else "Sin cita"
            )
            tipo_counts = (
                tipo.groupby(["Tipo_Cirugia", "Estado"])
                .size().reset_index(name="Pacientes")
            )
            fig_tipo = px.bar(
                tipo_counts, x="Tipo_Cirugia", y="Pacientes", color="Estado",
                title="Tipo de cirugía: cobertura",
                labels={"Tipo_Cirugia": "Tipo de cirugía"},
                color_discrete_map={"Con cita": "#2ecc71", "Sin cita": "#e74c3c"},
                barmode="stack",
            )
            fig_tipo.update_layout(xaxis_tickangle=-25, legend_title_text="", height=340, margin={"t": 40, "b": 60, "l": 20, "r": 20})
            st.plotly_chart(fig_tipo, use_container_width=True)
        else:
            st.info("Sin datos para este filtro.")

    with r2c3:
        hp_threshold = st.session_state.get("hp_threshold", 60)
        if df_view is not None:
            hp_sin = df_view[(df_view["Prioridad"] >= hp_threshold) & df_view["Fecha_Intervencion"].isna()].copy()
            if not hp_sin.empty:
                bins2   = [0, 30, 60, 90, 180, 10_000]
                labels2 = ["< 30 d", "30–60 d", "60–90 d", "90–180 d", "> 180 d"]
                hp_sin["Tramo"] = pd.cut(hp_sin["Dias_Espera"], bins=bins2, labels=labels2, right=False)
                hp_counts = hp_sin["Tramo"].value_counts().reindex(labels2).fillna(0).reset_index()
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
                fig_hp.update_layout(showlegend=False, height=340, margin={"t": 40, "b": 40, "l": 20, "r": 20})
                st.plotly_chart(fig_hp, use_container_width=True)
            else:
                st.info(f"No hay pacientes con prioridad ≥{hp_threshold}% sin cita.")
        else:
            st.info("Sin datos para este filtro.")
        st.number_input(
            "Prioridad mínima (%)", min_value=0, max_value=100, value=hp_threshold, step=5, key="hp_threshold",
        )

    st.divider()

    # ── Heatmap de carga quirúrgica: quirófano × día de la semana ─────────────
    df_heat = df_filtered[df_filtered["Fecha_Intervencion"].notna()].copy()
    if not df_heat.empty:
        dias_es = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
        df_heat["_dow"]  = pd.to_datetime(df_heat["Fecha_Intervencion"], format="mixed").dt.dayofweek
        df_heat["_dow"]  = df_heat["_dow"].map({0:"Lunes",1:"Martes",2:"Miércoles",3:"Jueves",4:"Viernes"})
        df_heat = df_heat[df_heat["_dow"].notna()]
        heat_pivot = (
            df_heat.groupby(["Quirofano", "_dow"])["Duracion_Horas"]
            .sum().reset_index()
            .pivot(index="Quirofano", columns="_dow", values="Duracion_Horas")
            .reindex(columns=dias_es)
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
            fig_heat.update_layout(xaxis_title="", yaxis_title="", height=360, margin={"t": 40, "b": 20, "l": 100, "r": 20})
            st.plotly_chart(fig_heat, use_container_width=True)
        else:
            st.info("Sin datos suficientes para el heatmap.")
    else:
        st.info("Sin intervenciones planificadas.")


with tab2:
    _tab2_fn()

# TAB 3: PACIENTES 
@st.fragment
def _tab3_fn():
    # Contadores para forzar reset de los inputs tras confirmar acción
    if "cancel_id_v" not in st.session_state:
        st.session_state["cancel_id_v"] = 0
    if "man_id_v" not in st.session_state:
        st.session_state["man_id_v"] = 0

    if msg := st.session_state.pop("tab3_success", None):
        st.success(msg)

    cancel_col, assign_col = st.columns(2)

    MOTIVOS_CANCEL = ["Decisión del paciente", "No presentación", "Causa del hospital"]

    # Cancelar cita 
    with cancel_col:
        with st.container(border=True):
            st.subheader("Cancelar cita de intervención", divider="blue")

            # Reasignación pendiente tras cancelación por causa del hospital
            if "hospital_cancel" in st.session_state:
                hc = st.session_state["hospital_cancel"]
                st.info(
                    f"Cita cancelada de **{hc['id'][:8]}…** "
                    f"({hc['quirofano']} · {hc['fecha']}). "
                    "Asigna una nueva fecha o crea un hueco."
                )
                hc_svc  = hc["servicio"]
                hc_dur  = hc["duracion"]
                ta_hc   = load_pm_assignment()
                pm_hc   = next((r for r, s in ta_hc.items() if s == hc_svc), None)
                hc_rooms = ROOMS_BY_SERVICE.get(hc_svc, []) + ([pm_hc] if pm_hc else [])
                hc_ref  = st.date_input("A partir del día", value=date.today(), key="hc_ref_date")
                hc_slots = find_free_slots(
                    hc_rooms, hc_ref, hc_dur, df,
                    closed_days=load_closed_days(),
                    unavailable_specs=load_unavailable_specs(),
                )
                if hc_slots:
                    hc_labels = [
                        f"{s.strftime('%d/%m/%Y  %H:%M')}  —  {r}" for s, r in hc_slots
                    ]
                    hc_sel = st.radio("Nuevos huecos disponibles", options=hc_labels, key="hc_slot_radio")
                    hc_slot, hc_room = hc_slots[hc_labels.index(hc_sel)]
                    bc1, bc2 = st.columns(2)
                    if bc1.button("Confirmar nueva cita", type="primary", key="hc_confirm"):
                        hc_idx = df[df["ID_Paciente"] == hc["id"]].index[0]
                        df.loc[hc_idx, "Fecha_Intervencion"] = hc_slot.strftime("%Y-%m-%d %H:%M")
                        df.loc[hc_idx, "Quirofano"]          = hc_room
                        df.loc[hc_idx, "Prioridad"]          = calculate_priority(
                            hc["edad"], hc["tipo_cirugia"], hc["fecha_ingreso"],
                            hc_slot.strftime("%Y-%m-%d %H:%M"),
                        )
                        df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
                        load_data.clear()
                        del st.session_state["hospital_cancel"]
                        st.session_state["tab3_success"] = (
                            f"Reasignado: {hc['id'][:8]}… → {hc_room} "
                            f"{hc_slot.strftime('%d/%m/%Y %H:%M')}"
                        )
                        st.rerun(scope="app")
                    if bc2.button("Omitir (crear hueco)", key="hc_skip"):
                        save_gap(hc["fecha"], hc["quirofano"], hc_svc, hc_dur,
                                 hc["codigo_procedimiento"], hc["id"], "Causa del hospital")
                        del st.session_state["hospital_cancel"]
                        st.session_state["tab3_success"] = "Hueco registrado para asignación posterior."
                        st.rerun(scope="app")
                else:
                    st.warning("No se encontraron slots libres. Se creará un hueco.")
                    if st.button("Aceptar", key="hc_no_slots"):
                        save_gap(hc["fecha"], hc["quirofano"], hc_svc, hc_dur,
                                 hc["codigo_procedimiento"], hc["id"], "Causa del hospital")
                        del st.session_state["hospital_cancel"]
                        st.session_state["tab3_success"] = "Hueco registrado para asignación posterior."
                        st.rerun(scope="app")

            else:
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
                            matches[["ID_Paciente", "Descripcion_Diagnostico", "Quirofano", "Fecha_Intervencion"]],
                            use_container_width=True, hide_index=True,
                        )
                    elif len(matches) == 1:
                        selected_id = matches.iloc[0]["ID_Paciente"]
                        patient     = df[df["ID_Paciente"] == selected_id].iloc[0]
                        st.markdown(f"**Quirófano:** {patient['Quirofano']}  |  **Fecha:** {patient['Fecha_Intervencion']}  |  **Prioridad:** {patient['Prioridad']:.1f}%")

                        motivo = st.selectbox("Motivo de cancelación", options=MOTIVOS_CANCEL, key="motivo_cancel")

                        if st.button("Cancelar cita", type="primary"):
                            mask = df["ID_Paciente"] == selected_id
                            new_priority = calculate_priority(
                                int(patient["Edad"]), str(patient["Tipo_Cirugia"]),
                                str(patient["Fecha_Ingreso"]), None,
                            )
                            df.loc[mask, "Fecha_Intervencion"] = None
                            df.loc[mask, "Quirofano"]          = None
                            df.loc[mask, "Prioridad"]          = new_priority
                            df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
                            load_data.clear()
                            st.session_state["cancel_id_v"] += 1

                            if motivo == "Causa del hospital":
                                st.session_state["hospital_cancel"] = {
                                    "id":                selected_id,
                                    "servicio":          str(patient["Servicio"]),
                                    "quirofano":         str(patient["Quirofano"]),
                                    "fecha":             str(patient["Fecha_Intervencion"]),
                                    "duracion":          float(patient["Duracion_Horas"] or 1.0),
                                    "codigo_procedimiento": str(patient["Codigo_Procedimiento"]),
                                    "edad":              int(patient["Edad"]),
                                    "tipo_cirugia":      str(patient["Tipo_Cirugia"]),
                                    "fecha_ingreso":     str(patient["Fecha_Ingreso"]),
                                }
                            else:
                                save_gap(
                                    str(patient["Fecha_Intervencion"]),
                                    str(patient["Quirofano"]),
                                    str(patient["Servicio"]),
                                    float(patient["Duracion_Horas"] or 1.0),
                                    str(patient["Codigo_Procedimiento"]),
                                    selected_id,
                                    motivo,
                                )
                                st.session_state["tab3_success"] = f"Cita cancelada. Prioridad: {patient['Prioridad']:.1f}% → {new_priority:.1f}%"
                            st.rerun(scope="app")

    # Asignar cita manualmente 
    with assign_col:
        with st.container(border=True):
            st.subheader("Asignar cita manualmente", divider="blue")

            man_id = st.text_input("ID del paciente", placeholder="Escribe el ID...", key=f"man_id_{st.session_state['man_id_v']}")
            man_matches = (
                df[df["ID_Paciente"].str.startswith(man_id) & df["Fecha_Intervencion"].isna()]
                if man_id else pd.DataFrame()
            )
            if man_id and man_matches.empty:
                st.warning("No se encontró ningún paciente sin cita con ese ID.")
            elif len(man_matches) > 1:
                st.info(f"{len(man_matches)} coincidencias. Escribe más caracteres para filtrar.")
                st.dataframe(
                    man_matches[["ID_Paciente", "Servicio", "Descripcion_Diagnostico", "Prioridad"]],
                    use_container_width=True, hide_index=True,
                )
            elif len(man_matches) == 1:
                man_patient = man_matches.iloc[0]
                man_svc     = str(man_patient["Servicio"])
                man_dur     = float(man_patient.get("Duracion_Horas") or 1.0)

                st.markdown(
                    f"**Servicio:** {man_svc}  |  **Prioridad:** {man_patient['Prioridad']:.1f}%  |  "
                    f"**Duración:** {man_dur:.1f} h  |  **Ingreso:** {str(man_patient['Fecha_Ingreso'])[:10]}"
                )

                ta_man = load_pm_assignment()
                pm_man = next((r for r, s in ta_man.items() if s == man_svc), None)
                man_rooms    = ROOMS_BY_SERVICE.get(man_svc, []) + ([pm_man] if pm_man else [])
                man_ref_date = st.date_input("A partir del día", value=date.today(), key="man_date")

                free_slots = find_free_slots(
                    man_rooms, man_ref_date, man_dur, df,
                    closed_days=load_closed_days(),
                    unavailable_specs=load_unavailable_specs(),
                )
                if not man_rooms:
                    st.warning("No hay quirófanos definidos para este servicio.")
                elif not free_slots:
                    st.warning("No se encontraron huecos libres en los próximos 365 días.")
                else:
                    slot_labels = [
                        f"{slot.strftime('%d/%m/%Y  %H:%M')}  —  {room}"
                        for slot, room in free_slots
                    ]
                    sel_label = st.radio(
                        "Próximos huecos disponibles",
                        options=slot_labels,
                        key="man_slot_radio",
                    )
                    chosen_slot, chosen_room = free_slots[slot_labels.index(sel_label)]

                    if st.button("Confirmar cita", type="primary", key="btn_man_assign"):
                        idx = man_matches.index[0]
                        df.loc[idx, "Fecha_Intervencion"] = chosen_slot.strftime("%Y-%m-%d %H:%M")
                        df.loc[idx, "Quirofano"]          = chosen_room
                        df.loc[idx, "Prioridad"]          = calculate_priority(
                            int(man_patient["Edad"]),
                            str(man_patient["Tipo_Cirugia"]),
                            str(man_patient["Fecha_Ingreso"]),
                            chosen_slot.strftime("%Y-%m-%d %H:%M"),
                        )
                        df.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
                        load_data.clear()
                        st.session_state["man_id_v"] += 1
                        st.session_state["tab3_success"] = (
                            f"Cita asignada: {man_patient['ID_Paciente']} → "
                            f"{chosen_room}  {chosen_slot.strftime('%d/%m/%Y %H:%M')}"
                        )
                        st.rerun(scope="app")

    st.divider()
    with st.container(border=True):
        st.subheader("Huecos disponibles", divider="blue")

        gaps_df = load_gaps()
        if gaps_df.empty:
            st.info("No hay huecos disponibles actualmente.")
        else:
            gap_services = sorted(gaps_df["servicio"].dropna().unique())
            selected_gap_svc = st.selectbox(
                "Filtrar por servicio",
                options=["Todos"] + gap_services,
                key="gaps_svc_filter",
            )
            if selected_gap_svc != "Todos":
                gaps_df = gaps_df[gaps_df["servicio"] == selected_gap_svc]
    
            if gaps_df.empty:
                st.info(f"No hay huecos disponibles para {selected_gap_svc}.")
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
    
                    st.divider()
    
                    # ── Candidatos con carga bajo demanda ────────────────────────
                    page_size    = 3
                    off_key = f"cand_offset_{gap['id_gap']}"
                    if off_key not in st.session_state:
                        st.session_state[off_key] = 0
                    offset = st.session_state[off_key]
    
                    # find_candidates devuelve PAGE+1 filas: la extra indica si hay más
                    candidates = find_candidates(df, gap.to_dict(), n=page_size, offset=offset)
                    has_more   = len(candidates) > page_size
                    page_cands = candidates.head(page_size)
    
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
    
                        btn_cols = st.columns([2, 2, 6])
                        with btn_cols[0]:
                            if has_more:
                                if st.button("Otros candidatos", key=f"more_cand_{gap['id_gap']}"):
                                    st.session_state[off_key] = offset + page_size
                                    st.rerun()
                        with btn_cols[1]:
                            if offset > 0:
                                if st.button("Candidatos originales", key=f"reset_cand_{gap['id_gap']}"):
                                    st.session_state[off_key] = 0
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

    st.divider()
    st.subheader("Tabla de pacientes", divider="blue")

    tf1, tf2 = st.columns([2, 3])
    with tf1:
        table_svc_filter = st.selectbox(
            "Filtrar por servicio",
            options=["Todos"] + sorted(df["Servicio"].dropna().unique()),
            key="table_svc_filter",
        )
    with tf2:
        search_id = st.text_input(
            "Buscar por ID de paciente", placeholder="Escribe parte del ID…", key="table_search_id"
        )

    table_cols = [
        "ID_Paciente", "Edad", "Sexo", "Servicio", "Prioridad",
        "Fecha_Ingreso", "Fecha_Intervencion", "Quirofano", "Duracion_Horas",
        "Codigo_Diagnostico", "Descripcion_Diagnostico",
        "Codigo_Procedimiento", "Descripcion_Procedimiento",
        "Comorbilidades",
    ]
    editable_cols = {"Fecha_Ingreso", "Duracion_Horas", "Comorbilidades"}
    disabled_cols = [c for c in table_cols if c not in editable_cols]

    df_table = df if table_svc_filter == "Todos" else df[df["Servicio"] == table_svc_filter]
    if search_id:
        df_table = df_table[df_table["ID_Paciente"].str.contains(search_id, case=False, na=False)]
    # Recalcular prioridad antes de filtrar columnas (necesita Tipo_Cirugia).
    # Se leen los reference dates por servicio una sola vez para evitar leer
    # el fichero JSON en cada iteración.
    df_table = df_table.copy().reset_index(drop=True)
    df_table["_fi_dt"] = pd.to_datetime(df_table["Fecha_Intervencion"], errors="coerce")
    ref_by_service = {
        svc: get_reference_date(svc)
        for svc in df_table["Servicio"].dropna().unique()
    }
    today = date.today()
    df_table["Prioridad"] = [
        calculate_priority(
            int(row["Edad"]),
            str(row["Tipo_Cirugia"]),
            str(row["Fecha_Ingreso"]),
            reference_date=today if pd.notna(row["_fi_dt"]) else ref_by_service.get(str(row["Servicio"]), today),
        )
        for _, row in df_table.iterrows()
    ]
    df_table.drop(columns=["_fi_dt"], inplace=True)
    table = df_table[table_cols].copy()
    table["Fecha_Ingreso"]      = pd.to_datetime(table["Fecha_Ingreso"],      errors="coerce").dt.date
    table["Fecha_Intervencion"] = pd.to_datetime(table["Fecha_Intervencion"], errors="coerce")
    col_config = {
        "Prioridad": st.column_config.ProgressColumn(
            "Prioridad",
            help="Score 0–100: espera (40 %) + edad (30 %) + invasividad cirugía (30 %)",
            min_value=0, max_value=100, format="%.1f%%",
        ),
        "Fecha_Ingreso":      st.column_config.DateColumn("Fecha ingreso",    format="DD/MM/YYYY"),
        "Fecha_Intervencion": st.column_config.DatetimeColumn("Intervención",  format="DD/MM/YYYY HH:mm"),
        "Quirofano":          st.column_config.TextColumn("Quirófano"),
        "Duracion_Horas":     st.column_config.NumberColumn("Duración (h)",   min_value=0.5, step=0.5, format="%.1f h"),
        "Codigo_Diagnostico": st.column_config.TextColumn("Cód. diagnóstico"),
        "Descripcion_Diagnostico": st.column_config.TextColumn("Diagnóstico"),
        "Codigo_Procedimiento":    st.column_config.TextColumn("Cód. procedimiento"),
        "Descripcion_Procedimiento": st.column_config.TextColumn("Procedimiento"),
        "Comorbilidades":     st.column_config.TextColumn("Comorbilidades"),
    }

    if st.toggle("Habilitar edición", key="toggle_edit_table"):
        edited = st.data_editor(
            table, column_config=col_config,
            disabled=disabled_cols,
            use_container_width=True, height=500,
        )
        if st.button("Guardar cambios", key="btn_save_table"):
            df_updated = df.set_index("ID_Paciente").copy()
            edited_idx = edited.set_index("ID_Paciente")
            for col in editable_cols:
                df_updated[col] = df_updated[col].where(
                    ~df_updated.index.isin(edited_idx.index),
                    edited_idx[col],
                )
            df_updated.reset_index().to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
            load_data.clear()
            st.success("Cambios guardados.")
            st.rerun(scope="app")
    else:
        st.dataframe(table, column_config=col_config, use_container_width=True, height=500)

with tab3:
    _tab3_fn()

# ── TAB 4: PLANIFICACIÓN ──────────────────────────────────────────────────────
@st.fragment
def _tab4_fn():
    plan_col, delete_col = st.columns(2)

    # Planificar intervenciones
    with plan_col:
        with st.container(border=True):
            st.subheader("Planificar intervenciones", divider="blue")

            plan_service = st.selectbox(
                "Servicio", options=sorted(df["Servicio"].dropna().unique()), key="plan_svc",
            )
            plan_default_start = get_reference_date(plan_service)
            pd1, pd2 = st.columns(2)
            with pd1:
                plan_start = st.date_input("Desde", value=plan_default_start, key="plan_start")
            with pd2:
                plan_end = st.date_input("Hasta", value=plan_default_start + timedelta(weeks=2), key="plan_end")

            svc_mask = df["Servicio"] == plan_service
            n_total  = int(svc_mask.sum())
            n_sched  = int(df.loc[svc_mask, "Fecha_Intervencion"].notna().sum())
            st.caption(
                f"**{plan_service}** — {n_total} pacientes · "
                f"{n_sched} con cita · {n_total - n_sched} en espera"
            )

            pm_plan        = next((r for r, s in load_pm_assignment().items() if s == plan_service), None)
            service_rooms  = ROOMS_BY_SERVICE.get(plan_service, []) + ([pm_plan] if pm_plan else [])
            svc_specialists = specialists_for_service(plan_service, extra_rooms=[pm_plan] if pm_plan else [])
            spec_name_to_id = {s["name"]: s["id"] for s in svc_specialists}
            spec_id_to_name = {v: k for k, v in spec_name_to_id.items()}
            spec_options    = list(spec_name_to_id)
            time_options   = [f"{h:02d}:{m:02d}" for h in range(8, 22) for m in (0, 30)] + ["22:00"]

            with st.expander("Quirófanos no disponibles"):
                # Cargar filas del CSV para los quirófanos de este servicio
                cd_csv = load_closed_days_df()
                cd_svc = cd_csv[cd_csv["quirofano"].isin(service_rooms)].copy()
                cd_svc["fecha"] = pd.to_datetime(cd_svc["fecha"], errors="coerce").dt.date
                cd_init = pd.DataFrame({
                    "Quirófano": cd_svc["quirofano"].tolist(),
                    "Fecha":     cd_svc["fecha"].tolist(),
                }) if not cd_svc.empty else pd.DataFrame({"Quirófano": pd.Series(dtype=str), "Fecha": pd.Series(dtype="object")})

                closed_df = st.data_editor(
                    cd_init,
                    column_config={
                        "Quirófano": st.column_config.SelectboxColumn("Quirófano", options=service_rooms, required=True),
                        "Fecha":     st.column_config.DateColumn("Fecha", format="DD/MM/YYYY", required=True),
                    },
                    num_rows="dynamic", use_container_width=True, hide_index=True,
                    key=f"closed_days_editor_{plan_service}",
                )
                if not cd_init.empty and st.button("Limpiar restricciones", key=f"clear_cd_{plan_service}", type="tertiary"):
                    save_closed_days_for_rooms(service_rooms, [])
                    st.rerun()

            with st.expander("Especialistas no disponibles"):
                # Cargar filas del CSV para los especialistas de este servicio
                svc_spec_ids = list(spec_name_to_id.values())
                us_csv = load_unavailable_specs_df()
                us_svc = us_csv[us_csv["especialista_id"].isin(svc_spec_ids)].copy()
                us_init = pd.DataFrame({
                    "Especialista": us_svc["especialista_id"].map(spec_id_to_name).tolist(),
                    "Fecha":        pd.to_datetime(us_svc["fecha"], errors="coerce").dt.date.tolist(),
                    "Hora inicio":  us_svc["hora_inicio"].tolist(),
                    "Hora fin":     us_svc["hora_fin"].tolist(),
                }) if not us_svc.empty else pd.DataFrame({
                    "Especialista": pd.Series(dtype=str),
                    "Fecha":        pd.Series(dtype="object"),
                    "Hora inicio":  pd.Series(dtype=str),
                    "Hora fin":     pd.Series(dtype=str),
                })

                unavail_spec_df = st.data_editor(
                    us_init,
                    column_config={
                        "Especialista": st.column_config.SelectboxColumn("Especialista", options=spec_options, required=True),
                        "Fecha":        st.column_config.DateColumn("Fecha", format="DD/MM/YYYY", required=True),
                        "Hora inicio":  st.column_config.SelectboxColumn("Hora inicio", options=time_options),
                        "Hora fin":     st.column_config.SelectboxColumn("Hora fin",    options=time_options),
                    },
                    num_rows="dynamic", use_container_width=True, hide_index=True,
                    key=f"unavail_spec_editor_{plan_service}",
                )
                if not us_init.empty and st.button("Limpiar restricciones", key=f"clear_us_{plan_service}", type="tertiary"):
                    save_unavailable_specs_for_ids(svc_spec_ids, [])
                    st.rerun()
                if svc_specialists:
                    def spec_rooms(spec_id: str) -> list[str]:
                        return [r for r, specs in SPECIALISTS_BY_ROOM.items() if any(s["id"] == spec_id for s in specs)]
                    turno_label = {8: "mañana", 15: "tarde"}
                    spec_info = "  \n".join(
                        f"**{s['name']}** — {', '.join(spec_rooms(s['id']))} ({turno_label.get(s['start_hour'], '')})"
                        for s in svc_specialists
                    )
                    st.caption(spec_info)

            if st.button("Planificar", type="primary", key="btn_planificar"):
                if plan_start > plan_end:
                    st.error("La fecha de inicio debe ser anterior a la fecha de fin.")
                else:
                    # Guardar restricciones del editor al CSV
                    cd_rows = [
                        {"quirofano": str(r["Quirófano"]), "fecha": pd.to_datetime(r["Fecha"]).date().isoformat()}
                        for _, r in closed_df.dropna(subset=["Quirófano", "Fecha"]).iterrows()
                    ]
                    save_closed_days_for_rooms(service_rooms, cd_rows)

                    spec_data_by_id = {s["id"]: s for s in svc_specialists}
                    def _hm(val, default_h: int) -> tuple[int, int]:
                        if pd.isna(val):
                            return default_h, 0
                        t = datetime.strptime(str(val), "%H:%M")
                        return t.hour, t.minute

                    us_rows = []
                    for _, row in unavail_spec_df.dropna(subset=["Especialista", "Fecha"]).iterrows():
                        spec_id   = spec_name_to_id.get(str(row["Especialista"]))
                        spec_data = spec_data_by_id.get(spec_id) if spec_id else None
                        if not spec_data:
                            continue
                        us_rows.append({
                            "especialista_id":     spec_id,
                            "especialista_nombre": str(row["Especialista"]),
                            "fecha":               pd.to_datetime(row["Fecha"]).date().isoformat(),
                            "hora_inicio":         str(row.get("Hora inicio", f"{spec_data['start_hour']:02d}:00")),
                            "hora_fin":            str(row.get("Hora fin",    f"{spec_data['end_hour']:02d}:00")),
                        })
                    save_unavailable_specs_for_ids(svc_spec_ids, us_rows)

                    # Reconstruir dicts para el planificador desde los datos del editor
                    closed_days: dict[str, list[date]] = {}
                    for r in cd_rows:
                        closed_days.setdefault(r["quirofano"], []).append(date.fromisoformat(r["fecha"]))

                    unavailable_specs: dict[str, list[tuple[datetime, datetime]]] = {}
                    for _, row in unavail_spec_df.dropna(subset=["Especialista", "Fecha"]).iterrows():
                        spec_id   = spec_name_to_id.get(str(row["Especialista"]))
                        spec_data = spec_data_by_id.get(spec_id) if spec_id else None
                        if not spec_data:
                            continue
                        d            = pd.to_datetime(row["Fecha"]).date()
                        start_h, start_m = _hm(row["Hora inicio"], spec_data["start_hour"])
                        end_h,   end_m   = _hm(row["Hora fin"],    spec_data["end_hour"])
                        unavailable_specs.setdefault(spec_id, []).append((
                            datetime(d.year, d.month, d.day, start_h, start_m),
                            datetime(d.year, d.month, d.day, end_h,   end_m),
                        ))

                    # Cargar quirófano de tarde asignado a este servicio (si existe)
                    ta = load_pm_assignment()
                    pm_for_service = next(
                        (room for room, svc in ta.items() if svc == plan_service), None
                    )
                    df_new, n_new = service_planning(
                        df, plan_service, plan_end, plan_start,
                        closed_days or None, unavailable_specs or None,
                        pm_room=pm_for_service,
                    )
                    df_new.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
                    save_planning(plan_service, plan_end)

                    # Eliminar huecos cubiertos por la planificación
                    gaps_df = load_gaps()
                    if not gaps_df.empty:
                        assigned_slots = set(zip(
                            pd.to_datetime(
                                df_new.loc[df_new["Fecha_Intervencion"].notna(), "Fecha_Intervencion"],
                                format="mixed",
                            ).dt.strftime("%Y-%m-%d %H:%M"),
                            df_new.loc[df_new["Fecha_Intervencion"].notna(), "Quirofano"].astype(str),
                        ))
                        for _, gap in gaps_df.iterrows():
                            gap_key = (
                                pd.to_datetime(gap["fecha_intervencion"]).strftime("%Y-%m-%d %H:%M"),
                                str(gap["quirofano"]),
                            )
                            if gap_key in assigned_slots:
                                remove_gap(str(gap["id_gap"]))

                    load_data.clear()
                    st.success(
                        f"{n_new} pacientes asignados en **{plan_service}** "
                        f"({plan_start.strftime('%d/%m/%Y')} – {plan_end.strftime('%d/%m/%Y')})."
                    )
                    st.rerun(scope="app")

    # Borrar planificación
    with delete_col:
        with st.container(border=True):
            st.subheader("Borrar planificación", divider="blue")

            delete_service = st.selectbox(
                "Servicio", options=sorted(df["Servicio"].dropna().unique()), key="delete_svc",
            )
            dd1, dd2 = st.columns(2)
            with dd1:
                delete_start = st.date_input("Desde", value=date.today(), key="delete_start")
            with dd2:
                delete_end = st.date_input("Hasta", value=date.today() + timedelta(weeks=2), key="delete_end")

            # Previsualización: cuántas citas se borrarían con el filtro actual
            preview_slots = pd.to_datetime(df["Fecha_Intervencion"], errors="coerce", format="mixed")
            preview_mask  = (
                (df["Servicio"] == delete_service)
                & df["Fecha_Intervencion"].notna()
                & (preview_slots >= pd.Timestamp(delete_start))
                & (preview_slots < pd.Timestamp(delete_end + timedelta(days=1)))
            )
            st.caption(f"Citas encontradas con este filtro: **{int(preview_mask.sum())}**")

            if st.button("Borrar planificación", key="btn_delete_plan"):
                if delete_start > delete_end:
                    st.error("La fecha de inicio debe ser anterior a la fecha de fin.")
                else:
                    st.session_state["confirm_delete_plan"] = True

            if st.session_state.get("confirm_delete_plan"):
                n_preview = int(preview_mask.sum())
                st.warning(
                    f"Vas a eliminar **{n_preview}** cita(s) de **{delete_service}** "
                    f"entre el **{delete_start.strftime('%d/%m/%Y')}** y el **{delete_end.strftime('%d/%m/%Y')}**. "
                    "Esta acción no se puede deshacer."
                )
                c_ok, c_cancel, _ = st.columns([1, 1, 3])
                with c_ok:
                    if st.button("Confirmar borrado", type="primary", key="confirm_delete_btn"):
                        # Leer CSV fresco para no depender del df en memoria
                        df_del = pd.read_csv(CSV_PATH)
                        slots_del = pd.to_datetime(df_del["Fecha_Intervencion"], errors="coerce", format="mixed")
                        del_mask  = (
                            (df_del["Servicio"] == delete_service)
                            & df_del["Fecha_Intervencion"].notna()
                            & (slots_del >= pd.Timestamp(delete_start))
                            & (slots_del < pd.Timestamp(delete_end + timedelta(days=1)))
                        )
                        n_del = int(del_mask.sum())
                        df_del.loc[del_mask, ["Fecha_Intervencion", "Quirofano"]] = None
                        df_del.to_csv(CSV_PATH, index=False, encoding="utf-8-sig")
                        load_data.clear()
                        st.session_state.pop("confirm_delete_plan", None)
                        st.success(f"{n_del} cita(s) eliminadas de **{delete_service}**.")
                        st.rerun(scope="app")
                with c_cancel:
                    if st.button("Cancelar", key="cancel_delete_btn"):
                        st.session_state.pop("confirm_delete_plan", None)
                        st.rerun()

        st.divider()
        with st.container(border=True):
            st.subheader("Exportar planificación en PDF", divider="blue")

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

    st.divider()
    with st.container(border=True):
        st.subheader("Quirófanos de tarde", divider="blue")
        st.caption(
            "Asigna cada quirófano de tarde (TARDE-Q1, TARDE-Q2) al servicio que más impacto tendrá. "
            "La asignación se guarda y se usa al planificar intervenciones."
        )
    
        if st.button("Calcular impacto", key="btn_recalc_impact"):
            with st.spinner("Calculando impacto de quirófanos de tarde..."):
                st.session_state["pm_impact"] = compute_pm_impact(df)
    
        # Cargar asignación persistida
        pm_assignment = load_pm_assignment()
        svc_list = sorted(df["Servicio"].dropna().unique())
    
        col1, col2 = st.columns(2)
        new_assignment: dict[str, str] = {}
        for i, pm_room_name in enumerate(PM_ROOMS):
            col = col1 if i == 0 else col2
            with col:
                st.markdown(f"**{pm_room_name}**")
                # Mostrar tabla de impacto si ya se calculó
                if "pm_impact" in st.session_state:
                    impact = st.session_state["pm_impact"]
                    st.dataframe(
                        impact[["Servicio", "Sin cita", "Asignados (M)", "Dur. media (h)", "Impacto cap.", "Espera sim. (d)"]],
                        column_config={
                            "Impacto cap.": st.column_config.NumberColumn(
                                "Impacto cap.",
                                help="Fracción de pacientes sin cita que no caben en quirófanos de mañana (0 = todos asignados, 1 = ninguno asignado). Cuanto mayor, más necesita este servicio el quirófano de tarde.",
                            ),
                            "Espera sim. (d)": st.column_config.NumberColumn(
                                "Espera sim. (d)",
                                help="Demora media simulada en días si se añade el quirófano de tarde a este servicio durante las próximas 4 semanas.",
                            ),
                        },
                        use_container_width=True,
                        hide_index=True,
                        height=220,
                    )
                    options = ["(ninguno)"] + list(impact["Servicio"])
                else:
                    st.info("Pulsa **Calcular impacto** para ver la tabla de referencia.")
                    options = ["(ninguno)"] + svc_list
                # Servicio actualmente asignado (si existe)
                current_svc = pm_assignment.get(pm_room_name)
                default_idx  = options.index(current_svc) if current_svc in options else 0
                selected_svc = st.selectbox(
                    f"Asignar {pm_room_name} a",
                    options=options,
                    index=default_idx,
                    key=f"pm_assign_{pm_room_name}",
                )
                new_assignment[pm_room_name] = selected_svc if selected_svc != "(ninguno)" else ""
    
        if st.button("Guardar asignación de quirófanos de tarde", key="btn_save_pm"):
            clean = {k: v for k, v in new_assignment.items() if v}
            # Validar que cada quirófano se asigne a un servicio distinto
            assigned_svcs = list(clean.values())
            if len(assigned_svcs) != len(set(assigned_svcs)):
                st.error("Cada quirófano de tarde debe asignarse a un servicio diferente.")
            else:
                save_pm_assignment(clean)
                st.success("Asignación guardada.")
                st.rerun(scope="app")


    st.divider()
    with st.container(border=True):
        st.subheader("Calendario de quirófanos", divider="blue")

        cc1, cc2 = st.columns(2)
        with cc1:
            cal_service = st.selectbox(
                "Servicio", options=sorted(df["Servicio"].dropna().unique()), key="cal_service",
            )
        pm_cal    = next((r for r, s in load_pm_assignment().items() if s == cal_service), None)
        cal_rooms = ROOMS_BY_SERVICE.get(cal_service, []) + ([pm_cal] if pm_cal else [])
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
                    "extendedProps": {"servicio": row["Servicio"], "diagnostico": row["Descripcion_Diagnostico"]},
                })

            st_calendar(events=events, options={
                "initialView": "timeGridWeek",
                "headerToolbar": {"left": "prev,next today", "center": "title", "right": "dayGridMonth,timeGridWeek,timeGridDay"},
                "slotMinTime": "08:00:00", "slotMaxTime": "22:00:00",
                "locale": "es", "height": 500,
            })

with tab4:
    _tab4_fn()
