from fastapi import APIRouter, Request, Query, HTTPException, Header
from app.elasticsearch.client import ESClient, get_index_name
from app.db.postgres_client import postgres_client
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging
import time

# ── Response Models ────────────────────────────────────
class SearchResult(BaseModel):
    document_id: str
    title: Optional[str] = None
    filename: Optional[str] = None
    author: Optional[str] = None
    identifier: Optional[str] = None
    number: Optional[str] = None
    doc_status: Optional[str] = None
    doc_created_at: Optional[str] = None
    doc_completed_at: Optional[str] = None
    highlight: Dict[str, Any] = {}

class SearchResponse(BaseModel):
    total: int
    page: int
    results: List[SearchResult]

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/search", response_model=SearchResponse, summary="Search Documents", description="Lexical search across allowed documents")
async def search_documents_lexical(
    request: Request,
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    size: int = Query(10, ge=1, le=100),
    x_company_id: str = Header(None, alias="X-Company-ID")
):
    start_time = time.time()
    company_id = getattr(request.state, "company_id", None)
    user_info  = getattr(request.state, "user_info", None)

    user_id = user_info.get("id") or user_info.get("user_id") or user_info.get("sub") if user_info else None
    if not user_id:
        return {"total": 0, "page": page, "results": []}

    factory = postgres_client.get_session_factory()
    if not factory:
        return {"total": 0, "page": page, "results": []}

    # ── ✅ ОПТИМИЗИРОВАННЫЙ ЗАПРОС 1: UNION с индексами ──────────────
    t1_start = time.time()
    allowed_doc_ids = []
    async with factory() as session:
        try:
            # Шаг 1: Найти user_db_id (быстро благодаря индексу на kclock_id)
            res = await session.execute(text("""
                SELECT id FROM users WHERE kclock_id = :user_uuid LIMIT 1
            """), {"user_uuid": str(user_id)})
            
            user_row = res.first()
            if not user_row:
                logger.warning(f"User not found for kclock_id: {user_id}")
                return {"total": 0, "page": page, "results": []}
            
            user_db_id = user_row[0]
            
            # Шаг 2: UNION запрос - ОН ИСПОЛЬЗУЕТ ИНДЕКСЫ!
            # Первая часть: idx_document_created_by
            # Вторая часть: idx_task_assigned_to
            res = await session.execute(text("""
                SELECT id FROM document WHERE created_by = :user_db_id
                UNION ALL
                SELECT document_id FROM task WHERE assigned_to = :user_db_id
            """), {"user_db_id": user_db_id})
            
            allowed_doc_ids = list({str(row[0]) for row in res.all()})
            logger.info(f"⏱️ [QUERY 1] PG allowed_doc_ids (UNION ALL): {len(allowed_doc_ids)} docs in {time.time()-t1_start:.2f}s")
            
        except Exception as e:
            logger.exception("Error querying allowed docs")
            return {"total": 0, "page": page, "results": []}

    if not allowed_doc_ids:
        return {"total": 0, "page": page, "results": []}

    # ── Запрос 2: ES поиск с агрегацией ────────────────
    index_name = get_index_name(company_id) if company_id else "*_documents"
    client     = ESClient.get_client()

    search_body = {
        "from":  (page - 1) * size,
        "size":  size,
        "query": {
            "bool": {
                "must": [{
                    "multi_match": {
                        "query":     q,
                        "fields":    ["title^3", "content"],
                        "fuzziness": "AUTO",
                        "analyzer":  "russian_custom"
                    }
                }],
                "filter": [{"terms": {"document_id": allowed_doc_ids}}]
            }
        },
        "track_total_hits": True,
        "collapse": {
            "field": "document_id"
        },
        "highlight": {
            "fields":    {"content": {}},
            "pre_tags":  ["<mark>"],
            "post_tags": ["</mark>"]
        },
        "aggs": {
            "unique_docs": {
                "cardinality": {
                    "field": "document_id",
                    "precision_threshold": 40000
                }
            }
        }
    }

    t2_start = time.time()
    try:
        response = await client.search(index=index_name, body=search_body)
        hits     = response["hits"]["hits"]
        total_unique = response["aggregations"]["unique_docs"]["value"]
        
        logger.info(f"⏱️ [QUERY 2] ES search: {len(hits)} hits, {total_unique} unique docs in {time.time()-t2_start:.2f}s")

        if not hits:
            logger.info(f"✅ [TOTAL] No results in {time.time()-start_time:.2f}s")
            return {"total": 0, "page": page, "results": []}

        result_doc_ids = list({hit["_source"]["document_id"] for hit in hits})

        # ── Запрос 3: метаданные из PG ────────────────
        t3_start = time.time()
        doc_info_map = {}
        async with factory() as session:
            try:
                res = await session.execute(text("""
                    WITH completed_tasks AS (
                        SELECT DISTINCT ON (document_id) document_id, completed_at
                        FROM task
                        WHERE status = 'COMPLETED' 
                          AND action_required = 'REGISTER'
                          AND document_id = ANY(:doc_ids)
                        ORDER BY document_id, completed_at DESC
                    )
                    SELECT
                        d.id,
                        d.identifier,
                        d.number,
                        d.status,
                        d.created_at,
                        dt.title,
                        dt.filename,
                        ct.completed_at
                    FROM document d
                    LEFT JOIN document_translation dt ON dt.document_id = d.id
                    LEFT JOIN completed_tasks ct ON ct.document_id = d.id
                    WHERE d.id = ANY(:doc_ids)
                """), {"doc_ids": [int(d) for d in result_doc_ids if d.isdigit()]})

                for row in res.all():
                    doc_id = str(row.id)
                    if doc_id not in doc_info_map or row.title:
                        doc_info_map[doc_id] = {
                            "identifier":      row.identifier,
                            "number":          row.number,
                            "doc_status":      row.status,
                            "doc_created_at":  row.created_at.date().isoformat() if row.created_at else None,
                            "title":           row.title,
                            "filename":        row.filename,
                            "doc_completed_at":    row.completed_at.date().isoformat() if row.completed_at else None,
                        }
                logger.info(f"⏱️ [QUERY 3] PG metadata: {len(doc_info_map)} docs in {time.time()-t3_start:.2f}s")
            except Exception as e:
                logger.error(f"Error fetching doc metadata: {e}")

        # ── Формируем результат ───────────────────────
        seen_doc_ids = set()
        results      = []

        for hit in hits:
            source   = hit["_source"]
            doc_id   = source["document_id"]
            doc_data = doc_info_map.get(doc_id, {})

            if doc_id in seen_doc_ids:
                continue
            seen_doc_ids.add(doc_id)

            results.append({
                "document_id":    doc_id,
                "title":          doc_data.get("title") or source.get("title"),
                "filename":       doc_data.get("filename"),
                "author":         source.get("author"),
                "identifier":     doc_data.get("identifier"),
                "number":         doc_data.get("number"),
                "doc_status":     doc_data.get("doc_status"),
                "doc_created_at": doc_data.get("doc_created_at"),
                "doc_completed_at":   doc_data.get("doc_completed_at"),
                "highlight":      hit.get("highlight", {}),
            })

        total_time = time.time() - start_time
        logger.info(f"✅ [TOTAL] {len(results)} results (total unique: {total_unique}) in {total_time:.2f}s")
        
        return {
            "total":   total_unique,
            "page":    page,
            "results": results
        }

    except Exception as e:
        logger.error(f"Search error: {e}")
        return {"total": 0, "page": page, "results": []}