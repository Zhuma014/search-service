from .client import ESClient, get_index_name
import logging

logger = logging.getLogger(__name__)

DOCUMENTS_MAPPING = {
    "settings": {
        "analysis": {
            "filter": {
                "ru_stop":    {"type": "stop",    "stopwords": "_russian_"},
                "ru_stemmer": {"type": "stemmer", "language": "russian"},
            },
            "analyzer": {
                "russian_custom": {
                    "tokenizer": "standard",
                    "filter": ["lowercase", "ru_stop", "ru_stemmer"]
                }
            }
        }
    },
    "mappings": {
        "properties": {
            "document_id": {"type": "keyword"},
            "chunk_id":    {"type": "keyword"},
            "uuid":        {"type": "keyword"},
            "number":      {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "status":      {"type": "keyword"},
            "author":      {"type": "keyword"},
            "filename":    {"type": "text"},
            "title":       {"type": "text", "analyzer": "russian_custom"},
            "content":     {"type": "text", "analyzer": "russian_custom"},
            "created_at":  {"type": "date"},
            "embedding": {
                "type": "dense_vector",
                "dims": 384,
                "index": True,
                "similarity": "cosine"
            }
        }
    }
}

async def ensure_index(company_id: str):
    client = ESClient.get_client()
    index_name = get_index_name(company_id)
    
    exists = await client.indices.exists(index=index_name)
    if not exists:
        logger.info(f"Creating index {index_name}")
        await client.indices.create(index=index_name, **DOCUMENTS_MAPPING)
    else:
        logger.debug(f"Index {index_name} already exists")
