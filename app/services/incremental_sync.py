from app.db.postgres_client import postgres_client
from app.services.sync_service import sync_documents
from app.elasticsearch.client import ESClient, get_index_name
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
    try:
        async with factory() as session:
            res = await session.execute(text(
                "SELECT DISTINCT company_id FROM document WHERE company_id IS NOT NULL"
            ))
            company_ids = [str(row[0]) for row in res.all()]
    except Exception as e:
        logger.error(f"Incremental sync: failed to fetch company IDs: {e}")
        return {"synced": 0, "errors": 0}

    if not company_ids:
        logger.info("Incremental sync: no companies found, nothing to do")
        return {"synced": 0, "errors": 0}

    logger.info(f"Incremental sync started for {len(company_ids)} companies")

    for company_id in company_ids:
        last_sync = _last_sync_at.get(company_id, now - timedelta(hours=1))

        try:
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
        except Exception as e:
            logger.error(f"Incremental sync: failed to query docs for company {company_id}: {e}")
            continue

        if not doc_ids:
            logger.info(f"Incremental sync: company {company_id} — no new docs since {last_sync.isoformat()}")
        else:
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

        # ── Удалить из ES документы, которых больше нет в PG ──────────────
        total_deleted = await _cleanup_deleted_docs(company_id, factory)
        if total_deleted:
            logger.info(f"Incremental sync: company {company_id} — removed {total_deleted} deleted docs from ES")

        _last_sync_at[company_id] = now

    logger.info(f"Incremental sync done — synced: {total_synced}, errors: {total_errors}")
    return {"synced": total_synced, "errors": total_errors}


async def _cleanup_deleted_docs(company_id: str, factory) -> int:
    """
    Finds document_ids that exist in ES but are no longer in PG,
    and removes them from the ES index.
    Returns the number of deleted documents.
    """
    index_name = get_index_name(company_id)
    es_client  = ESClient.get_client()

    # 1. Get all unique document_ids from ES for this company
    try:
        resp = await es_client.search(
            index=index_name,
            body={
                "size": 0,
                "aggs": {
                    "all_doc_ids": {
                        "terms": {"field": "document_id", "size": 100000}
                    }
                }
            }
        )
        es_doc_ids = {
            b["key"] for b in resp["aggregations"]["all_doc_ids"]["buckets"]
        }
    except Exception as e:
        logger.error(f"Cleanup: failed to fetch ES doc IDs for company {company_id}: {e}")
        return 0

    if not es_doc_ids:
        return 0

    # 2. Check which of those still exist in PG
    try:
        async with factory() as session:
            res = await session.execute(text(
                "SELECT id FROM document WHERE id = ANY(:ids)"
            ), {"ids": [int(d) for d in es_doc_ids if d.isdigit()]})
            pg_doc_ids = {str(row[0]) for row in res.all()}
    except Exception as e:
        logger.error(f"Cleanup: failed to fetch PG doc IDs for company {company_id}: {e}")
        return 0

    # 3. IDs in ES but not in PG → deleted
    orphaned = es_doc_ids - pg_doc_ids
    if not orphaned:
        return 0

    logger.info(f"Cleanup: found {len(orphaned)} orphaned docs in ES for company {company_id}: {orphaned}")

    deleted_count = 0
    for doc_id in orphaned:
        try:
            resp = await es_client.delete_by_query(
                index=index_name,
                body={"query": {"term": {"document_id": doc_id}}}
            )
            deleted_count += 1
            logger.info(f"Cleanup: removed doc {doc_id} ({resp.get('deleted', 0)} chunks) from ES")
        except Exception as e:
            logger.error(f"Cleanup: failed to delete doc {doc_id} from ES: {e}")

    return deleted_count
