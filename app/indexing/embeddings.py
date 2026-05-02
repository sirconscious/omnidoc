from sentence_transformers import SentenceTransformer
from typing import List, Optional

_MODEL: Optional[SentenceTransformer] = None

# Upgrade: all-mpnet-base-v2 (768 dims) for better semantic accuracy
MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"

def _get_model() -> SentenceTransformer:
    global _MODEL
    if _MODEL is None:
        _MODEL = SentenceTransformer(MODEL_NAME)
    return _MODEL

def embed(text: str) -> List[float]:
    model = _get_model()
    return model.encode(text).tolist()

def batch_embed(texts: List[str]) -> List[List[float]]:
    model = _get_model()
    return model.encode(texts).tolist()
