from quirofanos import ROOMS_BY_SERVICE

SPECIALISTS_BY_ROOM: dict[str, list[dict]] = {
    # Traumatología y Cirugía Ortopédica — solo mañana
    "TRAU-Q1": [{"id": "TRAU-Q1M", "name": "Dr. Carlos Martínez",   "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    "TRAU-Q2": [{"id": "TRAU-Q2M", "name": "Dra. Ana Sánchez",      "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    "TRAU-Q3": [{"id": "TRAU-Q3M", "name": "Dr. Luis López",        "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    "TRAU-Q4": [{"id": "TRAU-Q4M", "name": "Dra. Carmen Vega",      "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    # Cirugía General y Aparato Digestivo — solo mañana
    "CGAD-Q1": [{"id": "CGAD-Q1M", "name": "Dr. Pablo García",      "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    "CGAD-Q2": [{"id": "CGAD-Q2M", "name": "Dra. Laura Fernández",  "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    "CGAD-Q3": [{"id": "CGAD-Q3M", "name": "Dr. Miguel Torres",     "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    # Urología — solo mañana
    "UROL-Q1": [{"id": "UROL-Q1M", "name": "Dr. Roberto Jiménez",   "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    "UROL-Q2": [{"id": "UROL-Q2M", "name": "Dra. Patricia Moreno",  "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    # Neurocirugía — solo mañana
    "NEUR-Q1": [{"id": "NEUR-Q1M", "name": "Dr. Andrés Ruiz",       "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    "NEUR-Q2": [{"id": "NEUR-Q2M", "name": "Dra. Sofía Díaz",       "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    # Cirugía Cardiovascular — solo mañana
    "CCAR-Q1": [{"id": "CCAR-Q1M", "name": "Dr. Francisco Herrera", "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    "CCAR-Q2": [{"id": "CCAR-Q2M", "name": "Dra. Elena Romero",     "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    # Angiología y Cirugía Vascular — solo mañana
    "ANGI-Q1": [{"id": "ANGI-Q1M", "name": "Dr. Javier Castro",     "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    # Oftalmología — solo mañana
    "OFTA-Q1": [{"id": "OFTA-Q1M", "name": "Dra. Isabel Ramos",     "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    "OFTA-Q2": [{"id": "OFTA-Q2M", "name": "Dr. Sergio Ortiz",      "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    # Otorrinolaringología — solo mañana
    "OTOR-Q1": [{"id": "OTOR-Q1M", "name": "Dra. Marta Navarro",    "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    # Cirugía Torácica — solo mañana
    "CTOR-Q1": [{"id": "CTOR-Q1M", "name": "Dra. Beatriz Iglesias", "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    # Cirugía Maxilofacial — solo mañana
    "CMXF-Q1": [{"id": "CMXF-Q1M", "name": "Dr. Raúl Guerrero",    "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    # Dermatología — solo mañana
    "DERM-Q1": [{"id": "DERM-Q1M", "name": "Dra. Natalia Campos",   "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    # Cirugía Plástica — solo mañana
    "CPLA-Q1": [{"id": "CPLA-Q1M", "name": "Dr. Víctor Mendoza",    "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    # Ginecología y Obstetricia — solo mañana
    "GINE-Q1": [{"id": "GINE-Q1M", "name": "Dra. Rosa Peña",        "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    "GINE-Q2": [{"id": "GINE-Q2M", "name": "Dr. Diego Vargas",      "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    # Cirugía Pediátrica — solo mañana
    "CPED-Q1": [{"id": "CPED-Q1M", "name": "Dra. Lucía Serrano",    "days": [0,1,2,3,4], "start_hour": 8, "end_hour": 15}],
    # Quirófanos flotantes de tarde (15–22) — asignados dinámicamente a servicios
    "TARDE-Q1": [{"id": "TARDE-Q1T", "name": "Dr. Marcos Delgado",  "days": [0,1,2,3,4], "start_hour": 15, "end_hour": 22}],
    "TARDE-Q2": [{"id": "TARDE-Q2T", "name": "Dra. Carmen Lozano",  "days": [0,1,2,3,4], "start_hour": 15, "end_hour": 22}],
}


def specialists_for_service(service: str, extra_rooms: list[str] | None = None) -> list[dict]:
    """Devuelve lista deduplicada de especialistas del servicio, incluyendo quirófanos extra."""
    rooms = ROOMS_BY_SERVICE.get(service, []) + (extra_rooms or [])
    seen, result = set(), []
    for room in rooms:
        for spec in SPECIALISTS_BY_ROOM.get(room, []):
            if spec["id"] not in seen:
                seen.add(spec["id"])
                result.append(spec)
    return result
