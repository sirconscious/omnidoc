from qdrant_client import QdrantClient
from app.indexing.embeddings import embed

client = QdrantClient(host="localhost", port=6333)

query = "java developer"

vector = embed(query)

# client.delete_collection(collection_name="documents")

results = client.query_points(
    collection_name="documents",
    query=vector,
    limit=5
)

for r in results.points:
    print("Score:", r.score)
    print("File:", r.payload.get("filename"))
    print("Text:", r.payload.get("text"))
    print("-----")

#curl -X DELETE http://localhost:6333/collections/documents
