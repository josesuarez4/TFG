import random
import sys
import uuid
from datetime import date, timedelta

import pandas as pd

from generar_lista_espera_openai import (
    GENERATOR_DIR,
    DASHBOARD_DIR,
    DIAG_DF,
    PATIENT_COLUMNS,
    WAITLIST_COLUMNS,
    _fix_surgery_type,
    _fix_procedure_side,
    _extract_laterality,
    _generate_clinical_data,
    _procedure_candidates,
    calculate_priority,
    service_by_procedure,
    fake,
)

from rae_cmbd_pesos import (
    sample_comorbidities_rae,
    sample_age_rae,
    select_diagnosis_rae,
)


# Duración media en horas por servicio
_AVERAGE_DURATION: dict[str, float] = {
    "Neurocirugía":                         3.5,
    "Cirugía Cardiovascular":               4.5,
    "Cirugía Torácica":                     3.0,
    "Angiología y Cirugía Vascular":        3.0,
    "Cirugía General y Aparato Digestivo":  3.5,
    "Traumatología y Cirugía Ortopédica":   3.5,
    "Cirugía Maxilofacial":                 4.5,
    "Cirugía Plástica":                     3.5,
    "Urología":                             2.5,
    "Ginecología y Obstetricia":            2.0,
    "Otorrinolaringología":                 3.0,
    "Oftalmología":                         2.5,
    "Dermatología":                         2.5,
    "Cirugía Pediátrica":                   2.0,
}

# Modificador de duración según tipo de cirugía
_SURGERY_TYPE_MOD: dict[str, float] = {
    "Abierta":              1.5,
    "Laparoscópica":        1.0,
    "Artroscópica":         0.75,
    "Endoscópica":          0.5,
    "Robótica":             1.25,
    "Mínimamente invasiva": 0.75,
    "Percutánea":           0.5,
    "No aplica":            1.0,
}


def _estimate_duration(service: str, surgery_type: str) -> float:
    """Duración estimada en horas redondeada a medias horas."""
    avg = _AVERAGE_DURATION.get(service, 2.0)
    mod = _SURGERY_TYPE_MOD.get(surgery_type, 1.0)
    return max(0.5, round(avg * mod * 2) / 2)


_PEDIATRIC_SERVICES = {
    "Cirugía General y Aparato Digestivo",
    "Urología",
    "Cirugía Plástica",
}


def _fetch_patient_clinical(_: int) -> dict:
    """Genera los datos clínicos del paciente vía API. Devuelve claves internas _service,
    _admission_date y _duration que consume generate_patient_rae para asignar el slot."""
    birth_date, age, sex = sample_age_rae(fake)
    diags         = select_diagnosis_rae(sex, age, DIAG_DF)
    comorbidities = sample_comorbidities_rae(sex, age)

    candidates = _procedure_candidates(diags, sex)
    clinical   = _generate_clinical_data(diags, candidates, sex, age, candidate_comorbidities=comorbidities)

    if not clinical.get("procedimiento_correcto", True):
        anatomy = clinical.get("anatomia_principal", "").strip()
        if anatomy:
            candidates = _procedure_candidates(diags, sex, query_override=anatomy)
            clinical   = _generate_clinical_data(diags, candidates, sex, age, candidate_comorbidities=comorbidities)

    d1       = diags[0]
    proc_idx = _fix_procedure_side(diags, candidates, clinical["numero_procedimiento"])
    proc     = candidates.iloc[proc_idx]
    service  = service_by_procedure(proc["Código"])

    if age < 16 and service in _PEDIATRIC_SERVICES:
        service = "Cirugía Pediátrica"

    surgery_type   = _fix_surgery_type(proc["Código"], clinical.get("tipo_cirugia", ""))
    admission_date = date.today() - timedelta(days=random.randint(0, 90))

    return {
        "_service":        service,
        "_admission_date": admission_date,
        "_duration":       _estimate_duration(service, surgery_type),
        "ID_Paciente":               str(uuid.uuid4()),
        "Fecha_Nacimiento":          birth_date,
        "Edad":                      age,
        "Sexo":                      sex,
        "Codigo_Diagnostico":      d1["Código"],
        "Descripcion_Diagnostico": d1["Descripción"],
        "Codigo_Procedimiento":      proc["Código"],
        "Descripcion_Procedimiento": proc["Descripción"],
        "Tipo_Cirugia":              surgery_type,
        "Servicio":                  service,
        "Lateralidad":               _extract_laterality(proc["Descripción"], clinical.get("lateralidad", "No aplica")),
        "Observaciones":             clinical.get("observaciones", ""),
        "Curso_Clinico":             clinical.get("curso_clinico", ""),
        "Intervenciones_Previas":    clinical.get("intervenciones_previas", "Ninguna"),
        "Otros_Parametros_Clinicos": clinical.get("otros_parametros", ""),
        "Comorbilidades":            clinical.get("comorbilidades", "Ninguna"),
    }


def generate_patient_rae() -> dict:
    """Genera un paciente con datos clínicos. La fecha de intervención se asigna desde el dashboard."""
    p        = _fetch_patient_clinical(0)
    priority = calculate_priority(
        p["Edad"], p["Tipo_Cirugia"],
        p["_admission_date"].strftime("%Y-%m-%d"),
        None,
    )
    return {
        **{k: v for k, v in p.items() if not k.startswith("_")},
        "Prioridad":          priority,
        "Fecha_Ingreso":      p["_admission_date"].strftime("%Y-%m-%d"),
        "Fecha_Intervencion": None,
        "Quirofano":          None,
        "Duracion_Horas":     p["_duration"],
    }


_CHECKPOINT_EVERY = 500   # guardar progreso cada N pacientes


def generate_dataset_rae(
    n: int = 500,
    checkpoint_path=None,
) -> pd.DataFrame:
    """Genera n pacientes de forma secuencial con checkpoint opcional.

    Si checkpoint_path apunta a un CSV existente, reanuda desde el último
    paciente guardado en lugar de empezar desde cero.
    """
    rows: list[dict] = []
    start_i = 0

    if checkpoint_path is not None and checkpoint_path.exists():
        prev = pd.read_csv(checkpoint_path)
        if not prev.empty:
            rows    = prev.to_dict("records")
            start_i = len(rows)
            print(f"  Reanudando desde paciente {start_i + 1} (checkpoint encontrado)")

    for i in range(start_i, n):
        print(f"  Generando paciente {i + 1}/{n}...", end="\r", flush=True)
        rows.append(generate_patient_rae())

        if checkpoint_path is not None and (i + 1) % _CHECKPOINT_EVERY == 0:
            pd.DataFrame(rows).to_csv(checkpoint_path, index=False, encoding="utf-8-sig")
            print(f"\n  [Checkpoint] {i + 1}/{n} guardados en {checkpoint_path}")

    print()
    return pd.DataFrame(rows)


if __name__ == "__main__":
    args = sys.argv[1:]
    n    = int(args[0]) if len(args) > 0 else 500

    GENERATOR_DIR.mkdir(exist_ok=True)
    DASHBOARD_DIR.mkdir(exist_ok=True)
    patients_path    = GENERATOR_DIR / "pacientes.csv"
    waitlist_path    = DASHBOARD_DIR / "lista_espera_quirurgica.csv"
    checkpoint_path  = GENERATOR_DIR / "checkpoint_rae.csv"

    print(f"Generando {n} pacientes con distribución RAE-CMBD 2022 + OpenAI...")
    df = generate_dataset_rae(n, checkpoint_path=checkpoint_path)

    df[PATIENT_COLUMNS].to_csv(patients_path, index=False, encoding="utf-8-sig")
    df[WAITLIST_COLUMNS].to_csv(waitlist_path, index=False, encoding="utf-8-sig")

    if checkpoint_path.exists():
        checkpoint_path.unlink()
        print("  [Checkpoint eliminado]")

    print(f"  -> {patients_path}")
    print(f"  -> {waitlist_path}")

    print(f"\n=== Estadísticas ===")
    print(f"  Total pacientes : {len(df)}")
    print(f"  Edad media      : {df['Edad'].mean():.1f} años")
    print(f"  Sexo H/M        : {(df['Sexo']=='Hombre').sum()} / {(df['Sexo']=='Mujer').sum()}")
    print(f"  Prioridad media : {df['Prioridad'].mean():.1f}")
    print(f"\n  Muestra:")
    for _, row in df.head(3).iterrows():
        print(f"    [{row['Codigo_Diagnostico']}] {row['Descripcion_Diagnostico'][:55]}")
        print(f"      -> [{row['Codigo_Procedimiento']}] {row['Descripcion_Procedimiento'][:55]}")
        print(f"         Servicio: {row['Servicio']}  |  Prioridad: {row['Prioridad']}")
        print()
