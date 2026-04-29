import logging
import urllib3
import warnings
from elasticsearch import Elasticsearch
from app.core.config import ES_HOST, ES_USER, ES_PASSWORD

urllib3.disable_warnings()
warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)

INDEX_PREFIX = "omnidoc_"


def get_es_client() -> Elasticsearch:
    client = Elasticsearch(
        ES_HOST,
        basic_auth=(ES_USER, ES_PASSWORD),
        verify_certs=False,
    )
    if not client.ping():
        raise ConnectionError(f"Cannot reach Elasticsearch at {ES_HOST}")
    return client


def collection_index_name(collection_id: str) -> str:
    return f"{INDEX_PREFIX}{collection_id}"


CHUNK_MAPPING = {
    "mappings": {
        "properties": {
            "doc_id":         {"type": "keyword"},
            "chunk_id":       {"type": "keyword"},
            "chunk_index":    {"type": "integer"},
            "filename":       {"type": "keyword"},
            "file_type":      {"type": "keyword"},
            "collection_id":  {"type": "keyword"},
            "text":           {"type": "text", "analyzer": "english"},
            "source_page":    {"type": "integer"},
            "source_section": {"type": "keyword"},
            "has_table":      {"type": "boolean"},
            "word_count":     {"type": "integer"},
            "created_at":     {"type": "date"},
        }
    },
    "settings": {
        "number_of_shards":   1,
        "number_of_replicas": 0,
    },
}


def create_collection_index(collection_id: str, es: Elasticsearch = None) -> bool:
    es = es or get_es_client()
    index = collection_index_name(collection_id)
    if es.indices.exists(index=index):
        logger.info("ES index already exists: %s", index)
        return False
    es.indices.create(index=index, body=CHUNK_MAPPING)
    logger.info("Created ES index: %s", index)
    return True
