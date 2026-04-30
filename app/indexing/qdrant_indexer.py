import uuid
from typing import List, Dict, Any
from qdrant_client import QdrantClient
from qdrant_client.http.models import PointStruct, VectorParams, Distance
from app.indexing.embeddings import batch_embed
from app.indexing.qdrant_client import get_qdrant_client

COLLECTION_NAME: str = "documents"
VECTOR_SIZE: int = 384
DISTANCE = Distance.COSINE

def _ensure_collection(client: QdrantClient) -> None:
    try:
        client.get_collection(collection_name=COLLECTION_NAME)
    except Exception:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=DISTANCE)
        )

def index_chunks(doc_id: str, filename: str, collection_id: str, chunks: List[Dict[str, Any]]) -> None:
    if not chunks:
        return

    client = get_qdrant_client()
    _ensure_collection(client=client)

    texts = [chunk["text"] for chunk in chunks]
    embeddings = batch_embed(texts=texts)

    points = [
        PointStruct(
            # Qdrant requires UUID or unsigned integer IDs; using UUID to ensure uniqueness
            id=str(uuid.uuid4()),
            vector=embeddings[i],
            payload={
                "doc_id": doc_id,
                "filename": filename,
                "chunk_index": chunk["index"],
                "text": chunk["text"],
                "collection_id": collection_id
            }
        )
        for i, chunk in enumerate(chunks)
    ]

    try:
        client.upsert(collection_name=COLLECTION_NAME, points=points)
    except Exception as e:
        raise RuntimeError(f"Failed to index chunks for doc {doc_id}: {str(e)}") from e
