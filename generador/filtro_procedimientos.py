import pandas as pd

# Sección X: operaciones raíz quirúrgicas permitidas (carácter 3)
_X_SURGICAL_ROOT_OPS = frozenset("CFGHKRSTUW")

# Raíces excluidas de sección 0: Inspection, Map, Change, Control, Alteration estética
_SEC0_ROOT_OPS_EXCLUDE = frozenset("JK230")

# Raíces + abordaje External (X) no quirúrgicos:
# S=Reposition, N=Release, D=Extraction, F=Fragmentation
_ROOT_OP_EXTERNAL_EXCLUDE = frozenset("SNDF")

# Fragmentation con abordaje Percutaneous/External = LEOC/ESWL (no quirófano)
_FRAGMENTATION_NOQX_APPROACHES = frozenset("3X")


def filter_surgical_procedures(raw_df: pd.DataFrame) -> pd.DataFrame:
    # Secciones 0 (Medical & Surgical) y X (New Technology)
    mask = (
        (raw_df["Código"].str[0] == "0") |
        (
            (raw_df["Código"].str[0] == "X") &
            (raw_df["Código"].str[2].isin(_X_SURGICAL_ROOT_OPS))
        )
    )
    df = raw_df[mask].copy()

    # Excluir cualificador X (Diagnóstico)
    df = df[df["Código"].str[6] != "X"]

    # Excluir raíces no quirúrgicas de sección 0
    df = df[~(
        (df["Código"].str[0] == "0") &
        (df["Código"].str[2].isin(_SEC0_ROOT_OPS_EXCLUDE))
    )]

    # Excluir manipulaciones externas no quirúrgicas
    df = df[~(
        (df["Código"].str[2].isin(_ROOT_OP_EXTERNAL_EXCLUDE)) &
        (df["Código"].str[4] == "X")
    )]

    # Excluir LEOC/ESWL
    df = df[~(
        (df["Código"].str[2] == "F") &
        (df["Código"].str[4].isin(_FRAGMENTATION_NOQX_APPROACHES))
    )]

    return df
