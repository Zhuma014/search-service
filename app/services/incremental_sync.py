from app.db.postgres_client import postgres_client
from app.services.sync_service import sync_documents
from sqlalchemy import text
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# Per-company last-scanned timestamp (in-memory, resets to now-1h on first run per company)
_last_sync_at: dict[str, datetime] = {}


async def run_incremental_sync() -> dict:
    """
    Hourly job. Finds documents that became new or newly accessible since
    the last run and syncs them to Elasticsearch.

    A document is considered "new or newly accessible" when:
      1. document.created_at > last_sync_at  (new document)
      2. A task row with created_at > last_sync_at points to it
         (document was just assigned to a user via a task)
    """
    now = datetime.utcnow()
    total_synced = 0
    total_errors = 0

    factory = postgres_client.get_session_factory()
    if not factory:
        logger.error("Incremental sync: DB not available")
        return {"synced": 0, "errors": 0}

    # Discover all company IDs present in the document table
    async with factory() as session:
        res = await session.execute(text(
            "SELECT DISTINCT company_id FROM document WHERE company_id IS NOT NULL"
        ))
        company_ids = [str(row[0]) for row in res.all()]

    if not company_ids:
        logger.info("Incremental sync: no companies found, nothing to do")
        return {"synced": 0, "errors": 0}

    logger.info(f"Incremental sync started for {len(company_ids)} companies")

    for company_id in company_ids:
        last_sync = _last_sync_at.get(company_id, now - timedelta(hours=1))

        async with factory() as session:
            res = await session.execute(text("""
                SELECT DISTINCT d.id
                FROM document d
                JOIN document_translation dt ON dt.document_id = d.id
                WHERE d.company_id = :company_id
                  AND dt.file_path IS NOT NULL AND dt.file_path != ''
                  AND dt.filename IS NOT NULL AND dt.filename != ''
                  AND (
                    d.created_at > :last_sync
                    OR EXISTS (
                        SELECT 1 FROM task t
                        WHERE t.document_id = d.id
                          AND t.completed_at > :last_sync
                    )
                  )
            """), {"company_id": int(company_id) if company_id.isdigit() else company_id,
                   "last_sync": last_sync})
            doc_ids = [str(row[0]) for row in res.all()]

        if not doc_ids:
            logger.info(f"Incremental sync: company {company_id} — no new docs since {last_sync.isoformat()}")
            _last_sync_at[company_id] = now
            continue

        logger.info(f"Incremental sync: company {company_id} — {len(doc_ids)} docs to sync")

        for doc_id in doc_ids:
            try:
                synced, errors = await sync_documents(company_id, doc_id)
                total_synced += synced
                total_errors += len(errors)
                if errors:
                    logger.warning(f"Incremental sync: doc {doc_id} errors: {errors}")
            except Exception as e:
                total_errors += 1
                logger.error(f"Incremental sync: failed to sync doc {doc_id}: {e}")

        _last_sync_at[company_id] = now

    logger.info(f"Incremental sync done — synced: {total_synced}, errors: {total_errors}")
    return {"synced": total_synced, "errors": total_errors}
