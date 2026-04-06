from app.db.postgres_client import postgres_client
from app.storage.minio_client import minio_client
from app.indexer.core import index_document_content
from config import settings
from sqlalchemy import text
import logging
import posixpath

logger = logging.getLogger(__name__)



def get_best_file(file_path: str) -> tuple[str, bytes]:
    
    client = minio_client.get_client()  # ← используем get_client()
    
    objects = list(client.list_objects(
        settings.MINIO_BUCKET,
        prefix=file_path
    ))

    if not objects:
        raise Exception(f"Нет файлов по пути {file_path}")

    pdf_files  = [o for o in objects if o.object_name.endswith('.pdf')
                  and '_signed' not in o.object_name]
    docx_files = [o for o in objects if o.object_name.endswith('.docx')]
    xlsx_files = [o for o in objects if o.object_name.endswith('.xlsx')]
    any_files  = [o for o in objects if not o.object_name.endswith('.htm')]

    target = None
    if pdf_files:
        target = pdf_files[0]
    elif docx_files:
        target = docx_files[0]
    elif xlsx_files:
        target = xlsx_files[0]
    elif any_files:
        target = any_files[0]

    if not target:
        raise Exception(f"Нет подходящих файлов в {file_path}")

    # Скачать через download_file метод
    content  = minio_client.download_file(target.object_name)
    filename = target.object_name.split('/')[-1]

    return filename, content


async def sync_documents(company_id: str = None, document_id: str = None):
    
    logger.info(f"Starting sync. Limit: {settings.SYNC_LIMIT}, Doc ID: {document_id}")

    factory = postgres_client.get_session_factory()
    if not factory:
        return 0, [{"error": "DB connection failed"}]

    synced_count = 0
    errors = []

    async with factory() as session:
        try:
            query_str = """
                SELECT
                    d.id, d.uuid, d.number, d.status, d.company_id,
                    d.created_at, d.created_by as author,
                    dt.filename, dt.file_path,
                    COALESCE(dt.title, d.number, dt.filename) as title
                FROM document d
                JOIN document_translation dt ON dt.document_id = d.id
                WHERE dt.file_path IS NOT NULL AND dt.file_path != ''
                AND dt.filename IS NOT NULL AND dt.filename != ''
            """

            params = {"limit": settings.SYNC_LIMIT}

            if company_id:
                query_str += " AND d.company_id = :company_id"
                params["company_id"] = int(company_id) if company_id.isdigit() else company_id

            if document_id:
                query_str += " AND d.id = :document_id"
                params["document_id"] = int(document_id) if document_id.isdigit() else document_id

            query_str += " ORDER BY d.id DESC LIMIT :limit"

            res = await session.execute(text(query_str), params)
            docs_metadata = [dict(row._mapping) for row in res.all()]

            logger.info(f"Found {len(docs_metadata)} documents to sync")

            for doc in docs_metadata:
                c_id      = str(doc.get('company_id'))
                file_path = doc.get('file_path', '')
                doc_id    = str(doc.get('id'))
                title     = doc.get('title') or doc.get('filename') or 'Untitled'

                try:
                    logger.info(f"Syncing doc {doc_id} ({doc.get('number')}) from {file_path}")

                    # 1. Найти и скачать лучший файл из MinIO
                    filename, content = get_best_file(file_path)

                    logger.info(f"Downloaded {filename} ({len(content)} bytes)")

                    # 2. Индексировать в ES
                    await index_document_content(
                        company_id=c_id,
                        content=content,
                        filename=filename,
                        title=f"Документ №{doc.get('number')}" if doc.get('number') else title,
                        document_id=doc_id,
                        metadata={
                            "uuid":       doc.get("uuid"),
                            "number":     doc.get("number"),
                            "status":     doc.get("status"),
                            "author":     str(doc.get("author")) if doc.get("author") else None,
                            "filename":   filename,
                            "file_path":  file_path,
                            "created_at": doc.get("created_at"),
                        }
                    )

                    synced_count += 1
                    logger.info(f"✓ Synced doc {doc_id}")

                except Exception as e:
                    logger.error(f"✗ Failed doc {doc_id}: {e}")
                    errors.append({"id": doc_id, "error": str(e)})

        except Exception as e:
            logger.error(f"Postgres query error: {e}")
            errors.append({"error": str(e)})

    logger.info(f"Sync done. Synced: {synced_count}, Errors: {len(errors)}")
    return synced_count, errors