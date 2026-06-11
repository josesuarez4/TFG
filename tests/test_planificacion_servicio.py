import pytest
import pandas as pd
from datetime import date, datetime, timedelta
from unittest.mock import patch

from planificador import service_planning, find_free_slots

_MONDAY = date(2026, 6, 15)
_SPECS  = [{"id": "TEST-M", "name": "Dr. Test",
            "days": [0, 1, 2, 3, 4], "start_hour": 8, "end_hour": 15}]


def _make_patients(n=3, service="Urología", duration=1.0, admission_days_ago=30):
    today = date.today()
    return pd.DataFrame([
        {
            "ID_Paciente":        f"P{i}",
            "Edad":               50,
            "Tipo_Cirugia":       "Laparoscópica",
            "Fecha_Ingreso":      (today - timedelta(days=admission_days_ago + i)).isoformat(),
            "Servicio":           service,
            "Duracion_Horas":     duration,
            "Prioridad":          50.0 + i * 10,
            "Fecha_Intervencion": None,
            "Quirofano":          None,
        }
        for i in range(n)
    ])


class TestServicePlanning:
    def test_asigna_pacientes(self):
        df  = _make_patients(n=2)
        end = _MONDAY + timedelta(weeks=4)
        with patch("planificador.ROOMS_BY_SERVICE", {"Urología": ["Q1"]}), \
             patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS}):
            _, n_assigned = service_planning(df, "Urología", end, _MONDAY)
        assert n_assigned > 0

    def test_contador_coincide_con_filas_asignadas(self):
        df  = _make_patients(n=3)
        end = _MONDAY + timedelta(weeks=8)
        with patch("planificador.ROOMS_BY_SERVICE", {"Urología": ["Q1"]}), \
             patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS}):
            result_df, n_assigned = service_planning(df, "Urología", end, _MONDAY)
        assert n_assigned == int(result_df["Fecha_Intervencion"].notna().sum())

    def test_no_modifica_citas_existentes(self):
        today = date.today()
        existing_slot = (today + timedelta(days=20)).isoformat() + " 08:00"
        df = pd.DataFrame([{
            "ID_Paciente": "P1", "Edad": 50, "Tipo_Cirugia": "Laparoscópica",
            "Fecha_Ingreso": (today - timedelta(days=30)).isoformat(),
            "Servicio": "Urología", "Duracion_Horas": 1.0, "Prioridad": 80.0,
            "Fecha_Intervencion": existing_slot, "Quirofano": "Q1",
        }])
        end = today + timedelta(weeks=8)
        with patch("planificador.ROOMS_BY_SERVICE", {"Urología": ["Q1"]}), \
             patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS}):
            result_df, n_assigned = service_planning(df, "Urología", end, today)
        assert result_df.iloc[0]["Fecha_Intervencion"] == existing_slot
        assert n_assigned == 0

    def test_respeta_minimo_14_dias_desde_ingreso(self):
        today = date.today()
        df = pd.DataFrame([{
            "ID_Paciente": "P1", "Edad": 50, "Tipo_Cirugia": "Laparoscópica",
            "Fecha_Ingreso": today.isoformat(),
            "Servicio": "Urología", "Duracion_Horas": 1.0, "Prioridad": 80.0,
            "Fecha_Intervencion": None, "Quirofano": None,
        }])
        end = today + timedelta(weeks=6)
        with patch("planificador.ROOMS_BY_SERVICE", {"Urología": ["Q1"]}), \
             patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS}):
            result_df, n_assigned = service_planning(df, "Urología", end, today)
        if n_assigned > 0:
            slot_dt = pd.to_datetime(result_df.iloc[0]["Fecha_Intervencion"])
            assert slot_dt.date() >= today + timedelta(days=14)

    def test_paciente_alta_prioridad_se_asigna_antes(self):
        today = date.today()
        df = pd.DataFrame([
            {"ID_Paciente": "HIGH", "Edad": 80, "Tipo_Cirugia": "Abierta",
             "Fecha_Ingreso": (today - timedelta(days=30)).isoformat(),
             "Servicio": "Urología", "Duracion_Horas": 1.0, "Prioridad": 95.0,
             "Fecha_Intervencion": None, "Quirofano": None},
            {"ID_Paciente": "LOW",  "Edad": 25, "Tipo_Cirugia": "Percutánea",
             "Fecha_Ingreso": (today - timedelta(days=30)).isoformat(),
             "Servicio": "Urología", "Duracion_Horas": 1.0, "Prioridad": 10.0,
             "Fecha_Intervencion": None, "Quirofano": None},
        ])
        end = _MONDAY + timedelta(weeks=8)
        with patch("planificador.ROOMS_BY_SERVICE", {"Urología": ["Q1"]}), \
             patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS}):
            result_df, _ = service_planning(df, "Urología", end, _MONDAY)
        high_slot = result_df.loc[result_df["ID_Paciente"] == "HIGH", "Fecha_Intervencion"].iloc[0]
        low_slot  = result_df.loc[result_df["ID_Paciente"] == "LOW",  "Fecha_Intervencion"].iloc[0]
        if high_slot and low_slot:
            assert high_slot <= low_slot

    def test_dias_cerrados_bloquean_asignacion(self):
        df  = _make_patients(n=1)
        end = _MONDAY + timedelta(weeks=4)
        closed = {"Q1": [_MONDAY + timedelta(days=i) for i in range(29)]}
        with patch("planificador.ROOMS_BY_SERVICE", {"Urología": ["Q1"]}), \
             patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS}):
            _, n_assigned = service_planning(df, "Urología", end, _MONDAY,
                                             closed_days=closed)
        assert n_assigned == 0

    def test_ventana_pasada_no_asigna(self):
        today = date.today()
        df = _make_patients(n=1)
        end = today - timedelta(days=10)  # ventana ya pasada
        with patch("planificador.ROOMS_BY_SERVICE", {"Urología": ["Q1"]}), \
             patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS}):
            _, n_assigned = service_planning(df, "Urología", end, today)
        assert n_assigned == 0


class TestFindFreeSlots:
    def _empty_df(self):
        return pd.DataFrame(columns=["Quirofano", "Fecha_Intervencion", "Duracion_Horas"])

    def test_devuelve_como_mucho_n_slots(self):
        with patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS}):
            slots = find_free_slots(["Q1"], _MONDAY, 1.0, self._empty_df(), n=3)
        assert len(slots) <= 3

    def test_slots_dentro_del_turno(self):
        with patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS}):
            slots = find_free_slots(["Q1"], _MONDAY, 1.0, self._empty_df(), n=5)
        for slot_dt, _ in slots:
            shift_start = datetime(slot_dt.year, slot_dt.month, slot_dt.day, 8, 0)
            shift_end   = datetime(slot_dt.year, slot_dt.month, slot_dt.day, 15, 0)
            assert slot_dt >= shift_start
            assert slot_dt + timedelta(hours=1) <= shift_end

    def test_respeta_slots_ocupados(self):
        existing = datetime(_MONDAY.year, _MONDAY.month, _MONDAY.day, 8, 0)
        df = pd.DataFrame([{
            "Quirofano": "Q1",
            "Fecha_Intervencion": existing.isoformat(),
            "Duracion_Horas": 1.0,
        }])
        with patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS}):
            slots = find_free_slots(["Q1"], _MONDAY, 1.0, df, n=1)
        if slots:
            slot_dt, _ = slots[0]
            # El slot encontrado no puede solapar con 8:00–9:30 (1h cirugía + 30min limpieza)
            block_end = existing + timedelta(hours=1, minutes=30)
            overlaps = slot_dt < block_end and slot_dt + timedelta(hours=1) > existing
            assert not overlaps

    def test_lista_vacia_devuelve_vacio(self):
        with patch("planificador.SPECIALISTS_BY_ROOM", {}):
            slots = find_free_slots([], _MONDAY, 1.0, self._empty_df(), n=3)
        assert slots == []

    def test_slot_incluye_quirofano(self):
        with patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS}):
            slots = find_free_slots(["Q1"], _MONDAY, 1.0, self._empty_df(), n=1)
        if slots:
            _, room = slots[0]
            assert room == "Q1"
