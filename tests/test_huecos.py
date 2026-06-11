import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import patch

from huecos import procedure_similarity, find_candidates
import huecos


def _make_df():
    return pd.DataFrame([
        {"ID_Paciente": "P1", "Servicio": "Urología", "Fecha_Intervencion": None,
         "Duracion_Horas": 2.0, "Codigo_Procedimiento": "0TB00ZZ", "Prioridad": 80.0},
        {"ID_Paciente": "P2", "Servicio": "Urología", "Fecha_Intervencion": None,
         "Duracion_Horas": 3.0, "Codigo_Procedimiento": "0TB04ZZ", "Prioridad": 60.0},
        {"ID_Paciente": "P3", "Servicio": "Urología", "Fecha_Intervencion": "2026-07-01 08:00",
         "Duracion_Horas": 2.0, "Codigo_Procedimiento": "0TB00ZZ", "Prioridad": 70.0},
        {"ID_Paciente": "P4", "Servicio": "Neurocirugía", "Fecha_Intervencion": None,
         "Duracion_Horas": 2.0, "Codigo_Procedimiento": "00B00ZZ", "Prioridad": 90.0},
    ])


def _make_gap(cancelled_id="PC"):
    return {
        "servicio":              "Urología",
        "duracion_horas":        2.5,
        "codigo_procedimiento":  "0TB00ZZ",
        "id_paciente_cancelado": cancelled_id,
    }


def _gaps_path(tmp_path) -> Path:
    return tmp_path / "gaps_disponibles.csv"


class TestProcedureSimilarity:
    def test_codigos_identicos(self):
        assert procedure_similarity("0FB03ZZ", "0FB03ZZ") == 1.0

    def test_codigos_totalmente_distintos(self):
        assert procedure_similarity("AAAAAAA", "BBBBBBB") == 0.0

    def test_solo_primer_caracter_coincide(self):
        sim = procedure_similarity("0XXXXXX", "0YYYYYYY")
        assert sim == pytest.approx(0.20)

    def test_dos_primeros_coinciden(self):
        sim = procedure_similarity("0FXXXXX", "0FYYYYY")
        assert sim == pytest.approx(0.40)

    def test_no_distingue_mayusculas(self):
        assert procedure_similarity("0fb03zz", "0FB03ZZ") == 1.0

    def test_codigos_cortos_no_falla(self):
        sim = procedure_similarity("0FB", "0FB")
        assert sim > 0.0

    def test_rango_0_1(self):
        sim = procedure_similarity("0FB03ZZ", "0TB04ZX")
        assert 0.0 <= sim <= 1.0


class TestFindCandidates:
    def test_filtra_por_servicio(self):
        result = find_candidates(_make_df(), _make_gap())
        assert all(result["Servicio"] == "Urología")

    def test_excluye_pacientes_con_cita(self):
        result = find_candidates(_make_df(), _make_gap())
        assert "P3" not in result["ID_Paciente"].values

    def test_excluye_paciente_cancelado(self):
        gap = _make_gap(cancelled_id="P1")
        result = find_candidates(_make_df(), gap)
        assert "P1" not in result["ID_Paciente"].values

    def test_restriccion_duracion(self):
        result = find_candidates(_make_df(), _make_gap())
        assert "P2" not in result["ID_Paciente"].values

    def test_columna_puntuacion_presente(self):
        result = find_candidates(_make_df(), _make_gap())
        assert "Puntuacion" in result.columns

    def test_ordenado_por_puntuacion_descendente(self):
        result = find_candidates(_make_df(), _make_gap(), n=10)
        scores = result["Puntuacion"].tolist()
        assert scores == sorted(scores, reverse=True)

    def test_df_vacio_devuelve_vacio(self):
        df = pd.DataFrame(columns=["ID_Paciente", "Servicio", "Fecha_Intervencion",
                                    "Duracion_Horas", "Codigo_Procedimiento", "Prioridad"])
        result = find_candidates(df, _make_gap())
        assert result.empty

    def test_paginacion_offset(self):
        r0 = find_candidates(_make_df(), _make_gap(), n=1, offset=0)
        r1 = find_candidates(_make_df(), _make_gap(), n=1, offset=1)
        if not r0.empty and not r1.empty:
            assert r0.iloc[0]["ID_Paciente"] != r1.iloc[0]["ID_Paciente"]


class TestLoadGaps:
    def test_devuelve_df_vacio_si_no_existe_fichero(self, tmp_path):
        gaps_path = _gaps_path(tmp_path)
        with patch.object(huecos, "GAPS_PATH", gaps_path):
            df = huecos.load_gaps()
        assert df.empty
        assert list(df.columns) == huecos._COLUMNS

    def test_devuelve_df_con_datos_guardados(self, tmp_path):
        gaps_path = _gaps_path(tmp_path)
        with patch.object(huecos, "GAPS_PATH", gaps_path):
            huecos.save_gap("2026-07-01 08:00", "Q1", "Urología", 1.5,
                            "0BN04ZZ", "P001", "Cancelación voluntaria")
            df = huecos.load_gaps()
        assert len(df) == 1
        assert df.iloc[0]["quirofano"] == "Q1"
        assert df.iloc[0]["servicio"] == "Urología"


class TestSaveGap:
    def test_crea_fichero_con_nuevo_gap(self, tmp_path):
        gaps_path = _gaps_path(tmp_path)
        with patch.object(huecos, "GAPS_PATH", gaps_path):
            huecos.save_gap("2026-07-01 08:00", "Q1", "Urología", 2.0,
                            "0BN04ZZ", "P001")
        assert gaps_path.exists()

    def test_acumula_multiples_gaps(self, tmp_path):
        gaps_path = _gaps_path(tmp_path)
        with patch.object(huecos, "GAPS_PATH", gaps_path):
            huecos.save_gap("2026-07-01 08:00", "Q1", "Urología", 1.0, "0BN04ZZ", "P001")
            huecos.save_gap("2026-07-02 10:00", "Q2", "Urología", 2.0, "0BN04ZZ", "P002")
            df = huecos.load_gaps()
        assert len(df) == 2

    def test_guarda_todos_los_campos(self, tmp_path):
        gaps_path = _gaps_path(tmp_path)
        with patch.object(huecos, "GAPS_PATH", gaps_path):
            huecos.save_gap(
                fecha_intervencion="2026-07-01 09:00",
                quirofano="Q3",
                servicio="Neurocirugía",
                duracion_horas=3.5,
                codigo_procedimiento="00N10ZZ",
                id_paciente_cancelado="P999",
                motivo_cancelacion="Complicación preoperatoria",
            )
            df = huecos.load_gaps()
        row = df.iloc[0]
        assert row["fecha_intervencion"] == "2026-07-01 09:00"
        assert row["servicio"] == "Neurocirugía"
        assert float(row["duracion_horas"]) == pytest.approx(3.5)
        assert row["motivo_cancelacion"] == "Complicación preoperatoria"

    def test_genera_id_gap_unico(self, tmp_path):
        gaps_path = _gaps_path(tmp_path)
        with patch.object(huecos, "GAPS_PATH", gaps_path):
            huecos.save_gap("2026-07-01 08:00", "Q1", "Urología", 1.0, "0BN04ZZ", "P001")
            huecos.save_gap("2026-07-01 10:00", "Q1", "Urología", 1.0, "0BN04ZZ", "P002")
            df = huecos.load_gaps()
        assert df["id_gap"].nunique() == 2

    def test_motivo_vacio_por_defecto(self, tmp_path):
        gaps_path = _gaps_path(tmp_path)
        with patch.object(huecos, "GAPS_PATH", gaps_path):
            huecos.save_gap("2026-07-01 08:00", "Q1", "Urología", 1.0, "0BN04ZZ", "P001")
            df = huecos.load_gaps()
        assert str(df.iloc[0]["motivo_cancelacion"]) in ("", "nan", "")


class TestRemoveGap:
    def test_elimina_gap_por_id(self, tmp_path):
        gaps_path = _gaps_path(tmp_path)
        with patch.object(huecos, "GAPS_PATH", gaps_path):
            huecos.save_gap("2026-07-01 08:00", "Q1", "Urología", 1.0, "0BN04ZZ", "P001")
            df_before = huecos.load_gaps()
            gap_id = df_before.iloc[0]["id_gap"]
            huecos.remove_gap(gap_id)
            df_after = huecos.load_gaps()
        assert gap_id not in df_after["id_gap"].values

    def test_conserva_otros_gaps(self, tmp_path):
        gaps_path = _gaps_path(tmp_path)
        with patch.object(huecos, "GAPS_PATH", gaps_path):
            huecos.save_gap("2026-07-01 08:00", "Q1", "Urología", 1.0, "0BN04ZZ", "P001")
            huecos.save_gap("2026-07-02 10:00", "Q2", "Urología", 2.0, "0BN04ZZ", "P002")
            df_before = huecos.load_gaps()
            gap_id = df_before.iloc[0]["id_gap"]
            huecos.remove_gap(gap_id)
            df_after = huecos.load_gaps()
        assert len(df_after) == 1

    def test_id_inexistente_no_elimina_nada(self, tmp_path):
        gaps_path = _gaps_path(tmp_path)
        with patch.object(huecos, "GAPS_PATH", gaps_path):
            huecos.save_gap("2026-07-01 08:00", "Q1", "Urología", 1.0, "0BN04ZZ", "P001")
            huecos.remove_gap("id-que-no-existe")
            df = huecos.load_gaps()
        assert len(df) == 1
