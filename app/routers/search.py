from fastapi import APIRouter, Request, Query, HTTPException, Header
from app.elasticsearch.client import ESClient, get_index_name
from app.db.postgres_client import postgres_client
from sqlalchemy import text
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/search")
async def search_documents_lexical(
    request: Request,
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_company_id: str = Header(None, alias="X-Company-ID")
):
    company_id = getattr(request.state, "company_id", None)
    user_info  = getattr(request.state, "user_info", None)

    user_id = user_info.get("id") or user_info.get("user_id") or user_info.get("sub") if user_info else None
    if not user_id:
        return {"total": 0, "page": page, "results": []}

    factory = postgres_client.get_session_factory()
    if not factory:
        return {"total": 0, "page": page, "results": []}

    # ── Запрос 1: только allowed_doc_ids ──────────────
    allowed_doc_ids = []
    async with factory() as session:
        try:
            res = await session.execute(text("""
                WITH matched_user AS (
                    SELECT id FROM users WHERE kclock_id = :user_uuid LIMIT 1
                )
                SELECT DISTINCT d.id
                FROM document d
                LEFT JOIN task t ON d.id = t.document_id
                WHERE d.created_by = (SELECT id FROM matched_user)
                   OR t.assigned_to = (SELECT id FROM matched_user)
            """), {"user_uuid": str(user_id)})
            allowed_doc_ids = [str(row[0]) for row in res.all()]
        except Exception as e:
            logger.error(f"Error querying allowed docs: {e}")
            return {"total": 0, "page": page, "results": []}

    if not allowed_doc_ids:
        return {"total": 0, "page": page, "results": []}

    # ── Запрос 2: ES поиск ────────────────────────────
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
        "highlight": {
            "fields":    {"content": {}},
            "pre_tags":  ["<mark>"],
            "post_tags": ["</mark>"]
        }
    }

    try:
        response = await client.search(index=index_name, body=search_body)
        hits     = response["hits"]["hits"]

        if not hits:
            return {"total": 0, "page": page, "results": []}

        result_doc_ids = list({hit["_source"]["document_id"] for hit in hits})

        # ── Запрос 3: метаданные из PG ────────────────
        # Объединяем с title из document_translation
        doc_info_map = {}
        async with factory() as session:
            try:
                res = await session.execute(text("""
                    SELECT
                        d.id,
                        d.identifier,
                        d.number,
                        d.status,
                        d.created_at,
                        d.updated_at,
                        dt.title,
                        dt.filename
                    FROM document d
                    LEFT JOIN document_translation dt ON dt.document_id = d.id
                    WHERE d.id = ANY(:doc_ids)
                """), {"doc_ids": [int(d) for d in result_doc_ids if d.isdigit()]})

                for row in res.all():
                    doc_id = str(row.id)
                    # Не перезаписываем если уже есть запись с title
                    if doc_id not in doc_info_map or row.title:
                        doc_info_map[doc_id] = {
                            "identifier":      row.identifier,
                            "number":          row.number,
                            "doc_status":      row.status,
                            "doc_created_at":  row.created_at.isoformat() if row.created_at else None,
                            "doc_updated_at":  row.updated_at.isoformat() if row.updated_at else None,
                            "title":           row.title,
                            "filename":        row.filename,
                        }
            except Exception as e:
                logger.error(f"Error fetching doc metadata: {e}")

        # ── Формируем результат ───────────────────────
        # Дедупликация — показываем один результат на документ
        seen_doc_ids = set()
        results      = []

        for hit in hits:
            source   = hit["_source"]
            doc_id   = source["document_id"]
            doc_data = doc_info_map.get(doc_id, {})

            # Пропускаем дубликаты чанков одного документа
            if doc_id in seen_doc_ids:
                continue
            seen_doc_ids.add(doc_id)

            results.append({
                "document_id":    doc_id,
                "title":          doc_data.get("title") or source.get("title"),  # свежий из PG
                "filename":       doc_data.get("filename"),
                "author":         source.get("author"),
                "identifier":     doc_data.get("identifier"),
                "number":         doc_data.get("number"),
                "doc_status":     doc_data.get("doc_status"),
                "doc_created_at": doc_data.get("doc_created_at"),
                "doc_updated_at": doc_data.get("doc_updated_at"),
                "highlight":      hit.get("highlight", {}),
            })

        return {
            "total":   response["hits"]["total"]["value"],
            "page":    page,
            "results": results
        }

    except Exception as e:
        logger.error(f"Search error: {e}")
        return {"total": 0, "page": page, "results": []}
