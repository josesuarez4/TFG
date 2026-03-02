import pandas as pd
import numpy as np
from datetime import datetime, timedelta

np.random.seed(42)

n = 1000

hospitales = ["Hospital A", "Hospital B", "Hospital C"]
operacion = [
    # Operaciones ortopédicas
    "Artroscopia de rodilla",
    "Prótesis de cadera",
    "Prótesis de rodilla",
    "Meniscectomía",
    "Fijación de fracturas",
    "Cirugía de columna",
    "Prótesis de hombro",
    "Reparación de ligamento cruzado",
    
    # Operaciones oftalmológicas
    "Cataratas",
    "Cirugía de glaucoma",
    "Cirugía de retina",
    "Corrección de estrabismo",
    
    # Operaciones cardiovasculares
    "Bypass coronario",
    "Angioplastia",
    "Marcapasos",
    "Reparación de válvula cardíaca",
    "Cirugía de aneurisma",
    
    # Operaciones gastrointestinales
    "Apendicectomía",
    "Colecistectomía",
    "Hernias",
    "Gastrectomía",
    "Cirugía de colon",
    "Cirugía de úlcera gástrica",
    
    # Operaciones ginecológicas y obstétricas
    "Histerectomía",
    "Cesárea",
    "Cirugía de ovarios",
    "Miomectomía",
    
    # Operaciones urológicas
    "Próstata",
    "Litotricia renal",
    "Cistectomía",
    "Vasectomía",
    
    # Operaciones otorrinolaringológicas
    "Amigdalectomía",
    "Cirugía de senos paranasales",
    "Septoplastia",
    "Cirugía de oído medio",
    
    # Operaciones de cirugía general
    "Cirugía de tiroides",
    "Cirugía de túnel carpiano",
    "Varices",
    "Mastectomía",
    "Biopsia de mama",
    
    # Operaciones neurológicas
    "Craneotomía",
    "Cirugía de hernia discal",
    "Derivación ventricular",
    
    # Operaciones torácicas
    "Cirugía de pulmón",
    "Toracotomía",
    
    # Otras operaciones especializadas
    "Cirugía bariátrica",
    "Trasplante renal",
    "Cirugía de melanoma",
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

df.to_csv("Datos/lista_simulada.csv", index=False)
