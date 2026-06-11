"""
Precalcula y guarda los embeddings de todos los procedimientos ICD-10-PCS.
Ejecutar una sola vez antes de usar el generador:

    python precalcular_embeddings.py
"""

# Bypass SSL en entornos con certificados corporativos
import httpx
_orig_client       = httpx.Client.__init__
_orig_async_client = httpx.AsyncClient.__init__
def _no_verify(self, *a, **kw):   kw.setdefault("verify", False); _orig_client(self, *a, **kw)
def _no_verify_a(self, *a, **kw): kw.setdefault("verify", False); _orig_async_client(self, *a, **kw)
httpx.Client.__init__      = _no_verify
httpx.AsyncClient.__init__ = _no_verify_a

from pathlib import Path

import numpy as np
import pandas as pd
from sentence_transformers import SentenceTransformer

from filtro_procedimientos import filter_surgical_procedures

BASE_DIR         = Path(__file__).parent.parent
DATA_DIR        = BASE_DIR / "datos"
GENERATOR_DIR    = BASE_DIR / "datos_generados" / "generador"
CACHE_EMBEDDINGS = GENERATOR_DIR / "proc_embeddings.npy"
MODEL_NAME    = "paraphrase-multilingual-MiniLM-L12-v2"


def main() -> None:
    if CACHE_EMBEDDINGS.exists():
        print(f"El fichero ya existe: {CACHE_EMBEDDINGS}")
        print("Bórralo manualmente para recalcular.")
        return

    print("Cargando procedimientos...")
    proc_raw = pd.read_csv(DATA_DIR / "Procedimientos_ES2026.csv", dtype=str)
    proc_df  = filter_surgical_procedures(proc_raw).reset_index(drop=True)
    print(f"  {len(proc_df)} procedimientos quirúrgicos (de {len(proc_raw)} totales).")

    print(f"\nCargando model '{MODEL_NAME}'...")
    model = SentenceTransformer(MODEL_NAME)

    print("\nCalculando embeddings...")
    embeddings = model.encode(
        proc_df["Descripción"].tolist(),
        normalize_embeddings=True,
        batch_size=256,
        show_progress_bar=True,
    )

    GENERATOR_DIR.mkdir(exist_ok=True)
    np.save(CACHE_EMBEDDINGS, embeddings)
    print(f"\nListo: {CACHE_EMBEDDINGS}  ({embeddings.shape}, {CACHE_EMBEDDINGS.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
