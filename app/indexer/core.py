from app.extractor.parser import extract_text
from app.elasticsearch.client import ESClient, get_index_name
from app.elasticsearch.indexes import ensure_index
from config import settings
import uuid
from datetime import datetime
import logging
from app.services.embeddings import get_embeddings


logger = logging.getLogger(__name__)



def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 200) -> list[str]:
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += chunk_size - overlap
    return chunks


async def index_document_content(
    company_id: str,
    content: bytes,
    filename: str,
    title: str,
    document_id: str = None,
    metadata: dict = None
):
    # Создать индекс если не существует
    await ensure_index(company_id)

    # Извлечь текст из файла
    text = extract_text(filename, content)
    if not text or not text.strip():
        raise Exception(f"Не удалось извлечь текст из {filename}")

    doc_id     = document_id or str(uuid.uuid4())
    index_name = get_index_name(company_id)
    client     = ESClient.get_client()

    # Нарезать на чанки
    chunks = chunk_text(text)
    logger.info(f"Doc {doc_id}: {len(chunks)} chunks from {filename}")

    # Векторизовать локально — без API, без лимитов
    embeddings = get_embeddings(chunks)

    # Обработать метаданные
    metadata   = metadata or {}
    created_at = metadata.get("created_at")
    if created_at and isinstance(created_at, datetime):
        created_at = created_at.isoformat()
    elif not created_at:
        created_at = datetime.utcnow().isoformat()

    # Индексировать чанки в ES
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings)):
        doc = {
            "document_id": doc_id,
            "chunk_id":    f"{doc_id}_{i}",
            "uuid":        metadata.get("uuid"),
            "number":      metadata.get("number"),
            "status":      metadata.get("status"),
            "author":      metadata.get("author"),
            "filename":    metadata.get("filename") or filename,
            "title":       title,
            "content":     chunk,
            "created_at":  created_at,
            "embedding":   embedding
        }
        await client.index(
            index=index_name,
            id=doc["chunk_id"],
            document=doc
        )

    await client.indices.refresh(index=index_name)
    logger.info(f"✓ Indexed doc {doc_id} — {len(chunks)} chunks")

    return {
        "document_id":  doc_id,
        "chunks_count": len(chunks),
        "text_length":  len(text)
    }