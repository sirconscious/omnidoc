import logging
from datetime import datetime, timezone
from elasticsearch import helpers
from app.indexing.es_client import get_es_client, collection_index_name

logger = logging.getLogger(__name__)


def index_document_chunks(
    doc_id: str,
    collection_id: str,
    filename: str,
    file_type: str,
    chunks: list,
    created_at: str = None,
) -> dict:
    if not chunks:
        return {"indexed": 0, "failed": 0, "errors": []}

    if created_at is None:
        created_at = datetime.now(timezone.utc).isoformat()

    es = get_es_client()
    index = collection_index_name(collection_id)

    # Auto-create index if it doesn't exist yet
    if not es.indices.exists(index=index):
        from app.indexing.es_client import create_collection_index
        create_collection_index(collection_id, es=es)

    actions = []
    for chunk in chunks:
        chunk_index = chunk.get("index", 0)
        chunk_id    = f"{doc_id}_chunk_{chunk_index}"
        actions.append({
            "_index": index,
            "_id":    chunk_id,
            "_source": {
                "doc_id":         doc_id,
                "chunk_id":       chunk_id,
                "chunk_index":    chunk_index,
                "filename":       filename,
                "file_type":      file_type,
                "collection_id":  collection_id,
                "text":           chunk.get("text", ""),
                "source_page":    chunk.get("source_page"),
                "source_section": chunk.get("source_section"),
                "has_table":      chunk.get("has_table", False),
                "word_count":     chunk.get("word_count", 0),
                "created_at":     created_at,
            },
        })

    success_count, errors = helpers.bulk(es, actions, raise_on_error=False, stats_only=False)

    if errors:
        logger.error("ES indexing had %d failures for doc %s", len(errors), doc_id)
    else:
        logger.info("ES indexed %d chunks for doc %s into %s", success_count, doc_id, index)

    return {"indexed": success_count, "failed": len(errors), "errors": errors}
