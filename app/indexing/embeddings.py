from sentence_transformers import SentenceTransformer
from typing import List, Optional

_MODEL: Optional[SentenceTransformer] = None

def _get_model() -> SentenceTransformer:
    global _MODEL
    if _MODEL is None:
        _MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return _MODEL

def embed(text: str) -> List[float]:
    model = _get_model()
    return model.encode(text).tolist()

def batch_embed(texts: List[str]) -> List[List[float]]:
    model = _get_model()
    return model.encode(texts).tolist()
