# app/embeddings.py
from sentence_transformers import SentenceTransformer
import logging

logger = logging.getLogger(__name__)

embedding_model = None

def _load_model():
    """Lazy load embedding model only when needed"""
    global embedding_model
    if embedding_model is None:
        logger.info("Loading embedding model multilingual-e5-small...")
        embedding_model = SentenceTransformer("intfloat/multilingual-e5-small")
        logger.info("✓ Embedding model loaded")
    return embedding_model


def get_embeddings(texts: list[str]) -> list[list[float]]:
    """Для индексации — префикс passage:"""
    if not texts:
        return []
    model = _load_model()
    prefixed   = [f"passage: {t}" for t in texts]
    embeddings = model.encode(prefixed, normalize_embeddings=True)
    return embeddings.tolist()


def get_query_embedding(text: str) -> list[float]:
    """Для поиска — префикс query:"""
    model = _load_model()
    embedding = model.encode(f"query: {text}", normalize_embeddings=True)
    return embedding.tolist()