import pytest
import pandas as pd
from datetime import date, datetime
from unittest.mock import patch

import restricciones as rc


def _closed_df(rows):
    return pd.DataFrame(rows, columns=["quirofano", "fecha"])


def _unavail_df(rows):
    return pd.DataFrame(rows, columns=["especialista_id", "especialista_nombre",
                                        "fecha", "hora_inicio", "hora_fin"])


class TestLoadClosedDays:
    def test_parsea_fechas_validas(self):
        df = _closed_df([
            {"quirofano": "Q1", "fecha": "2026-07-01"},
            {"quirofano": "Q1", "fecha": "2026-07-02"},
        ])
        with patch.object(rc, "load_closed_days_df", return_value=df):
            result = rc.load_closed_days()
        assert date(2026, 7, 1) in result["Q1"]
        assert date(2026, 7, 2) in result["Q1"]

    def test_omite_fechas_invalidas(self):
        df = _closed_df([
            {"quirofano": "Q1", "fecha": "no-es-fecha"},
            {"quirofano": "Q1", "fecha": "2026-07-01"},
        ])
        with patch.object(rc, "load_closed_days_df", return_value=df):
            result = rc.load_closed_days()
        assert len(result.get("Q1", [])) == 1

    def test_agrupa_por_quirofano(self):
        df = _closed_df([
            {"quirofano": "Q1", "fecha": "2026-07-01"},
            {"quirofano": "Q2", "fecha": "2026-07-02"},
        ])
        with patch.object(rc, "load_closed_days_df", return_value=df):
            result = rc.load_closed_days()
        assert "Q1" in result and "Q2" in result
        assert "Q1" not in [str(d) for d in result.get("Q2", [])]

    def test_df_vacio_devuelve_dict_vacio(self):
        df = pd.DataFrame(columns=["quirofano", "fecha"])
        with patch.object(rc, "load_closed_days_df", return_value=df):
            result = rc.load_closed_days()
        assert result == {}

    def test_multiples_quirofanos_mismo_dia(self):
        df = _closed_df([
            {"quirofano": "Q1", "fecha": "2026-07-01"},
            {"quirofano": "Q2", "fecha": "2026-07-01"},
        ])
        with patch.object(rc, "load_closed_days_df", return_value=df):
            result = rc.load_closed_days()
        assert date(2026, 7, 1) in result["Q1"]
        assert date(2026, 7, 1) in result["Q2"]


class TestLoadUnavailableSpecs:
    def test_parsea_periodo_completo(self):
        df = _unavail_df([{
            "especialista_id": "SPEC-1", "especialista_nombre": "Dr. Test",
            "fecha": "2026-07-01", "hora_inicio": "09:00", "hora_fin": "12:00",
        }])
        with patch.object(rc, "load_unavailable_specs_df", return_value=df):
            result = rc.load_unavailable_specs()
        start, end = result["SPEC-1"][0]
        assert start == datetime(2026, 7, 1, 9, 0)
        assert end   == datetime(2026, 7, 1, 12, 0)

    def test_omite_fecha_invalida(self):
        df = _unavail_df([{
            "especialista_id": "SPEC-1", "especialista_nombre": "Dr. Test",
            "fecha": "invalida", "hora_inicio": "09:00", "hora_fin": "12:00",
        }])
        with patch.object(rc, "load_unavailable_specs_df", return_value=df):
            result = rc.load_unavailable_specs()
        assert "SPEC-1" not in result

    def test_omite_horas_invalidas(self):
        df = _unavail_df([{
            "especialista_id": "SPEC-1", "especialista_nombre": "Dr. Test",
            "fecha": "2026-07-01", "hora_inicio": "nan", "hora_fin": "nan",
        }])
        with patch.object(rc, "load_unavailable_specs_df", return_value=df):
            result = rc.load_unavailable_specs()
        assert "SPEC-1" not in result

    def test_acumula_multiples_periodos_por_especialista(self):
        df = _unavail_df([
            {"especialista_id": "SPEC-1", "especialista_nombre": "Dr. Test",
             "fecha": "2026-07-01", "hora_inicio": "08:00", "hora_fin": "10:00"},
            {"especialista_id": "SPEC-1", "especialista_nombre": "Dr. Test",
             "fecha": "2026-07-02", "hora_inicio": "13:00", "hora_fin": "15:00"},
        ])
        with patch.object(rc, "load_unavailable_specs_df", return_value=df):
            result = rc.load_unavailable_specs()
        assert len(result["SPEC-1"]) == 2

    def test_df_vacio_devuelve_dict_vacio(self):
        df = pd.DataFrame(columns=["especialista_id", "especialista_nombre",
                                    "fecha", "hora_inicio", "hora_fin"])
        with patch.object(rc, "load_unavailable_specs_df", return_value=df):
            result = rc.load_unavailable_specs()
        assert result == {}

    def test_distintos_especialistas_separados(self):
        df = _unavail_df([
            {"especialista_id": "SPEC-1", "especialista_nombre": "Dr. A",
             "fecha": "2026-07-01", "hora_inicio": "08:00", "hora_fin": "10:00"},
            {"especialista_id": "SPEC-2", "especialista_nombre": "Dr. B",
             "fecha": "2026-07-01", "hora_inicio": "10:00", "hora_fin": "12:00"},
        ])
        with patch.object(rc, "load_unavailable_specs_df", return_value=df):
            result = rc.load_unavailable_specs()
        assert len(result["SPEC-1"]) == 1
        assert len(result["SPEC-2"]) == 1
