import pytest
from datetime import date, datetime, timedelta
from unittest.mock import patch

from planificador import _specialist_available, _assign_slot

_MONDAY   = date(2026, 6, 15)
_SATURDAY = date(2026, 6, 20)

_SPECS_MAÑANA = [{"id": "TEST-M", "name": "Dr. Test",
                  "days": [0, 1, 2, 3, 4], "start_hour": 8, "end_hour": 15}]

_SPECS_DIA_COMPLETO = [{"id": "TEST-M", "name": "Dr. Test",
                        "days": [0, 1, 2, 3, 4], "start_hour": 8, "end_hour": 22}]


class TestSpecialistAvailable:
    def test_sin_especialistas_retorna_true(self):
        with patch("planificador.SPECIALISTS_BY_ROOM", {}):
            s = datetime(2026, 6, 15, 8, 0)
            e = datetime(2026, 6, 15, 9, 0)
            assert _specialist_available("QUIROFANO_INEXISTENTE", s, e, {}) is True

    def test_dentro_de_turno(self):
        s = datetime(2026, 6, 15, 8, 0)
        e = datetime(2026, 6, 15, 9, 0)
        with patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS_MAÑANA}):
            assert _specialist_available("Q1", s, e, {}) is True

    def test_fuera_de_turno_fin(self):
        # Cirugía acaba a las 15:30, turno termina a las 15:00
        s = datetime(2026, 6, 15, 14, 0)
        e = datetime(2026, 6, 15, 15, 30)
        with patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS_MAÑANA}):
            assert _specialist_available("Q1", s, e, {}) is False

    def test_limite_exacto_de_turno(self):
        # 8:00 + 7h = 15:00, que coincide exactamente con el fin de turno
        s = datetime(2026, 6, 15, 8, 0)
        e = datetime(2026, 6, 15, 15, 0)
        with patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS_MAÑANA}):
            assert _specialist_available("Q1", s, e, {}) is True

    def test_especialista_no_disponible(self):
        s = datetime(2026, 6, 15, 9, 0)
        e = datetime(2026, 6, 15, 10, 0)
        unavail = {"TEST-M": [(datetime(2026, 6, 15, 8, 0), datetime(2026, 6, 15, 12, 0))]}
        with patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS_MAÑANA}):
            assert _specialist_available("Q1", s, e, unavail) is False

    def test_no_disponible_fuera_de_rango(self):
        # La no disponibilidad es por la tarde; la cirugía es por la mañana
        s = datetime(2026, 6, 15, 8, 0)
        e = datetime(2026, 6, 15, 9, 0)
        unavail = {"TEST-M": [(datetime(2026, 6, 15, 13, 0), datetime(2026, 6, 15, 15, 0))]}
        with patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS_MAÑANA}):
            assert _specialist_available("Q1", s, e, unavail) is True

    def test_dia_no_laborable(self):
        # Sábado = weekday 5, especialista solo trabaja 0-4
        s = datetime(2026, 6, 20, 8, 0)
        e = datetime(2026, 6, 20, 9, 0)
        with patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS_MAÑANA}):
            assert _specialist_available("Q1", s, e, {}) is False


class TestAssignSlot:
    def test_sin_quirofanos_retorna_none(self):
        with patch("planificador.ROOMS_BY_SERVICE", {}):
            room, slot = _assign_slot("ServicioInexistente", _MONDAY,
                                      _MONDAY + timedelta(days=7), 1.0, {})
            assert room is None and slot is None

    def test_asigna_primer_slot_disponible(self):
        with patch("planificador.ROOMS_BY_SERVICE", {"Svc": ["Q1"]}), \
             patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS_MAÑANA}):
            room, slot = _assign_slot("Svc", _MONDAY, _MONDAY + timedelta(days=7), 1.0, {})
            assert room == "Q1"
            assert slot == "2026-06-15 08:00"

    def test_salta_fines_de_semana(self):
        with patch("planificador.ROOMS_BY_SERVICE", {"Svc": ["Q1"]}), \
             patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS_MAÑANA}):
            room, slot = _assign_slot("Svc", _SATURDAY, _SATURDAY + timedelta(days=7), 1.0, {})
            assert room is not None
            dt = datetime.strptime(slot, "%Y-%m-%d %H:%M")
            assert dt.weekday() < 5

    def test_respeta_slots_ocupados(self):
        # 8:00–9:30 ocupado (1h cirugía + 30min limpieza) → siguiente libre: 9:30
        used = {"Q1": [(datetime(2026, 6, 15, 8, 0), datetime(2026, 6, 15, 9, 30))]}
        with patch("planificador.ROOMS_BY_SERVICE", {"Svc": ["Q1"]}), \
             patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS_MAÑANA}):
            room, slot = _assign_slot("Svc", _MONDAY, _MONDAY, 1.0, used)
            assert slot == "2026-06-15 09:30"

    def test_cirugia_no_supera_cierre_22h(self):
        # Con turno extendido y 7h de cirugía: último inicio válido = 15:00
        used = {}
        with patch("planificador.ROOMS_BY_SERVICE", {"Svc": ["Q1"]}), \
             patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS_DIA_COMPLETO}):
            room, slot = _assign_slot("Svc", _MONDAY, _MONDAY + timedelta(days=3), 7.0, used)
            if room:
                dt  = datetime.strptime(slot, "%Y-%m-%d %H:%M")
                end = dt + timedelta(hours=7)
                or_close = datetime(dt.year, dt.month, dt.day, 22, 0)
                assert end <= or_close

    def test_retorna_none_sin_huecos(self):
        # Todo el día bloqueado
        used = {"Q1": [(datetime(2026, 6, 15, 0, 0), datetime(2026, 6, 15, 23, 59))]}
        with patch("planificador.ROOMS_BY_SERVICE", {"Svc": ["Q1"]}), \
             patch("planificador.SPECIALISTS_BY_ROOM", {"Q1": _SPECS_MAÑANA}):
            room, slot = _assign_slot("Svc", _MONDAY, _MONDAY, 1.0, used)
            assert room is None and slot is None

    def test_rooms_override(self):
        # rooms_override ignora ROOMS_BY_SERVICE
        with patch("planificador.ROOMS_BY_SERVICE", {"Svc": ["Q_IGNORADO"]}), \
             patch("planificador.SPECIALISTS_BY_ROOM", {"Q_REAL": _SPECS_MAÑANA}):
            room, slot = _assign_slot("Svc", _MONDAY, _MONDAY + timedelta(days=3),
                                      1.0, {}, rooms_override=["Q_REAL"])
            assert room == "Q_REAL"
