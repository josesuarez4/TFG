import json
import pytest
from datetime import date, timedelta
from unittest.mock import patch

import registro_planificacion as pl


class TestGetReferenceDate:
    def test_servicio_desconocido_devuelve_hoy(self):
        with patch.object(pl, "_load_raw", return_value={}):
            assert pl.get_reference_date("Servicio Inexistente") == date.today()

    def test_devuelve_dia_siguiente_al_ultimo_horizonte(self):
        last_end = date.today() + timedelta(days=20)
        with patch.object(pl, "_load_raw", return_value={"Urología": last_end.isoformat()}):
            assert pl.get_reference_date("Urología") == last_end + timedelta(days=1)

    def test_nunca_devuelve_fecha_pasada(self):
        last_end = date.today() - timedelta(days=30)
        with patch.object(pl, "_load_raw", return_value={"Urología": last_end.isoformat()}):
            result = pl.get_reference_date("Urología")
        assert result >= date.today()

    def test_multiples_servicios_independientes(self):
        log = {
            "Urología":    (date.today() + timedelta(days=10)).isoformat(),
            "Neurocirugía": (date.today() + timedelta(days=20)).isoformat(),
        }
        with patch.object(pl, "_load_raw", return_value=log):
            ref_urol = pl.get_reference_date("Urología")
            ref_neur = pl.get_reference_date("Neurocirugía")
        assert ref_neur > ref_urol


class TestSavePlanning:
    def test_roundtrip_save_get(self, tmp_path):
        log_path = tmp_path / "planning_log.json"
        with patch.object(pl, "_LOG_PATH", log_path):
            pl.save_planning("Urología", date(2026, 9, 1))
            result = pl.get_reference_date("Urología")
        assert result == date(2026, 9, 2)

    def test_sobreescribe_planificacion_anterior(self, tmp_path):
        log_path = tmp_path / "planning_log.json"
        with patch.object(pl, "_LOG_PATH", log_path):
            pl.save_planning("Urología", date(2026, 8, 1))
            pl.save_planning("Urología", date(2026, 9, 1))
            raw = json.loads(log_path.read_text())
        assert raw["Urología"] == "2026-09-01"

    def test_multiples_servicios_no_se_sobreescriben(self, tmp_path):
        log_path = tmp_path / "planning_log.json"
        with patch.object(pl, "_LOG_PATH", log_path):
            pl.save_planning("Urología",    date(2026, 8, 1))
            pl.save_planning("Neurocirugía", date(2026, 9, 1))
            raw = json.loads(log_path.read_text())
        assert "Urología" in raw and "Neurocirugía" in raw

    def test_fichero_corrupto_no_falla(self, tmp_path):
        log_path = tmp_path / "planning_log.json"
        log_path.write_text("{ invalid json", encoding="utf-8")
        with patch.object(pl, "_LOG_PATH", log_path):
            result = pl.get_reference_date("Urología")
        assert result == date.today()
