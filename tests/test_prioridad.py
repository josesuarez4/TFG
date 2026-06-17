import pytest
from datetime import date, timedelta
from prioridad import calculate_priority, _age_pct


class TestAgePct:
    def test_neonato_maximo(self):
        assert _age_pct(0) == 100.0

    def test_adolescente_minimo_local(self):
        # La curva en U tiene su mínimo alrededor de los 14 años
        assert _age_pct(14) < _age_pct(0)
        assert _age_pct(14) < _age_pct(80)

    def test_anciano_maximo(self):
        assert _age_pct(90) == 100.0

    def test_adulto_medio(self):
        # 45 años debe estar por debajo de los extremos
        assert _age_pct(45) < _age_pct(0)
        assert _age_pct(45) < _age_pct(90)

    def test_curva_creciente_adultos(self):
        # A partir de la adolescencia la curva sube con la edad
        assert _age_pct(30) < _age_pct(60) < _age_pct(80)


class TestCalculatePriority:
    _HOY = date.today()
    _INGRESO_RECIENTE = (_HOY - timedelta(days=30)).isoformat()
    _INGRESO_LARGO    = (_HOY - timedelta(days=200)).isoformat()

    def test_resultado_entre_0_y_100(self):
        p = calculate_priority(50, "Abierta", self._INGRESO_LARGO)
        assert 0.0 <= p <= 100.0

    def test_mayor_espera_mayor_prioridad(self):
        p_reciente = calculate_priority(50, "Laparoscópica", self._INGRESO_RECIENTE)
        p_largo    = calculate_priority(50, "Laparoscópica", self._INGRESO_LARGO)
        assert p_largo > p_reciente

    def test_cirugia_abierta_mayor_que_percutanea(self):
        p_abierta   = calculate_priority(50, "Abierta",    self._INGRESO_LARGO)
        p_percutanea = calculate_priority(50, "Percutánea", self._INGRESO_LARGO)
        assert p_abierta > p_percutanea

    def test_ranking_tipos_cirugia(self):
        p_abierta      = calculate_priority(50, "Abierta",               self._INGRESO_LARGO)
        p_robotica     = calculate_priority(50, "Robótica",              self._INGRESO_LARGO)
        p_artroscopica = calculate_priority(50, "Artroscópica",          self._INGRESO_LARGO)
        p_percutanea   = calculate_priority(50, "Percutánea",            self._INGRESO_LARGO)
        assert p_abierta > p_robotica > p_artroscopica > p_percutanea

    def test_tipo_desconocido_no_lanza_error(self):
        p = calculate_priority(50, "Desconocida", self._INGRESO_LARGO)
        assert 0.0 <= p <= 100.0

    def test_espera_mayor_de_un_año_satura(self):
        ingreso_dos_años = (self._HOY - timedelta(days=800)).isoformat()
        p = calculate_priority(50, "Percutánea", ingreso_dos_años)
        assert p <= 100.0

    def test_fecha_intervencion_limita_espera(self):
        # Con fecha de intervención asignada, la espera no sigue creciendo
        interv = (self._HOY - timedelta(days=50)).isoformat()
        p_con    = calculate_priority(50, "Laparoscópica", self._INGRESO_LARGO, intervention_date=interv)
        p_sin    = calculate_priority(50, "Laparoscópica", self._INGRESO_LARGO)
        assert p_con < p_sin

    def test_reference_date_sustituye_hoy(self):
        ref = self._HOY - timedelta(days=10)
        p_ref = calculate_priority(50, "Laparoscópica", self._INGRESO_LARGO, reference_date=ref)
        p_hoy = calculate_priority(50, "Laparoscópica", self._INGRESO_LARGO)
        # La reference_date es 10 días antes → menos espera → menor prioridad
        assert p_ref < p_hoy

    def test_ingreso_hoy_espera_cero(self):
        p = calculate_priority(50, "Percutánea", self._HOY.isoformat())
        # wait_pct = 0, surg_pct = 0 → solo componente de edad
        expected_age = _age_pct(50) * 0.35
        assert p == pytest.approx(expected_age, abs=0.2)
