import pandas as pd
import numpy as np
from datetime import datetime, timedelta

np.random.seed(42)

n = 1000

hospitales = ["Hospital A", "Hospital B", "Hospital C"]
operacion = [
    "Artroscopia de rodilla",
    "Cataratas",
    "Prótesis de cadera",
    "Prótesis de rodilla",
    "Hernias",
    "Colecistectomía",
    "Bypass coronario",
    "Angioplastia",
    "Marcapasos",
    "Apendicectomía",
    "Cirugía de columna",
    "Histerectomía",
    "Cesárea",
    "Amigdalectomía",
    "Meniscectomía",
    "Fijación de fracturas",
    "Cirugía de túnel carpiano",
    "Varices",
    "Cirugía de tiroides",
    "Próstata"
]
prioridades = ["Urgente", "Preferente", "Normal"]

fechas_entrada = [datetime(2026,1,1) + timedelta(days=np.random.randint(0,730)) for _ in range(n)]
estados = np.random.choice(["En espera", "Intervenido", "Cancelado"], n, p=[0.7, 0.25, 0.05])

# Generar fechas de intervención: None para algunos "En espera" y "Cancelado", fechas para "Intervenido" y algunos "En espera"
fechas_intervencion = []
for i in range(n):
    if estados[i] == "Intervenido":
        # Intervenidos siempre tienen fecha
        fechas_intervencion.append(fechas_entrada[i] + timedelta(days=np.random.randint(1,180)))
    elif estados[i] == "En espera":
        # 50% de los que están en espera tienen fecha programada
        if np.random.random() < 0.5:
            fechas_intervencion.append(fechas_entrada[i] + timedelta(days=np.random.randint(1,180)))
        else:
            fechas_intervencion.append(None)
    else:  # Cancelado
        # 80% de cancelados no tienen fecha
        if np.random.random() < 0.2:
            fechas_intervencion.append(fechas_entrada[i] + timedelta(days=np.random.randint(1,180)))
        else:
            fechas_intervencion.append(None)

data = {
  "paciente_id": range(1, n+1),
  "hospital": np.random.choice(hospitales, n),
  "operacion": np.random.choice(operacion, n),
  "prioridad": np.random.choice(prioridades, n),
  "fecha_entrada": fechas_entrada,
  "fecha_intervencion": fechas_intervencion,
  "estado": estados
}

df = pd.DataFrame(data)

df.to_csv("Datos/lista_espera_simulada.csv", index=False)
