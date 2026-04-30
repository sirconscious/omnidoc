from qdrant_client import QdrantClient
from app.core.config import QDRANT_HOST, QDRANT_PORT

def get_qdrant_client() -> QdrantClient:
    if not QDRANT_HOST:
        raise ValueError("QDRANT_HOST environment variable is not set")
    if not QDRANT_PORT:
        raise ValueError("QDRANT_PORT environment variable is not set")
    return QdrantClient(host=QDRANT_HOST, port=int(QDRANT_PORT))
