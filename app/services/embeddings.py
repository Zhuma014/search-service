# app/embeddings.py
from sentence_transformers import SentenceTransformer
import logging

logger = logging.getLogger(__name__)

logger.info("Loading embedding model multilingual-e5-small...")
embedding_model = SentenceTransformer("intfloat/multilingual-e5-small")
logger.info("✓ Embedding model loaded")


def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Для индексации — префикс passage:"""
    if not texts:
        return []
    prefixed   = [f"passage: {t}" for t in texts]
    embeddings = embedding_model.encode(prefixed, normalize_embeddings=True)
    return embeddings.tolist()


def get_query_embedding(text: str) -> list[float]:
    """Для поиска — префикс query:"""
    embedding = embedding_model.encode(f"query: {text}", normalize_embeddings=True)
    return embedding.tolist()