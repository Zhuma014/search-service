from fastapi import APIRouter, Request, Query, HTTPException, Header
from app.elasticsearch.client import ESClient, get_index_name
from pydantic import BaseModel
from typing import List, Optional
import logging

# ── Response Models ────────────────────────────────────
class DocumentItem(BaseModel):
    document_id: str
    title: str
    created_at: str

class DocumentListResponse(BaseModel):
    total: int
    page: int
    size: int
    documents: List[DocumentItem]

class DocumentDeleteResponse(BaseModel):
    document_id: str
    deleted_chunks: int
    status: str

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("/documents", response_model=DocumentListResponse, summary="List Documents", description="Get paginated list of all documents in the index")
async def list_documents(
    request: Request,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    x_company_id: str = Header(..., alias="X-Company-ID")
):
    company_id = getattr(request.state, "company_id", None)
    if not company_id:
        raise HTTPException(status_code=400, detail="Company ID missing")

    index_name = get_index_name(company_id)
    client = ESClient.get_client()
    
    try:
        # Use collapse to get unique documents by document_id
        # We need to sort by created_at to get the most recent ones
        search_body = {
            "from": (page - 1) * size,
            "size": size,
            "query": {"match_all": {}},
            "collapse": {
                "field": "document_id"
            },
            "sort": [{"created_at": "desc"}]
        }
        
        response = await client.search(index=index_name, body=search_body)
        
        documents = []
        for hit in response["hits"]["hits"]:
            source = hit["_source"]
            documents.append({
                "document_id": source["document_id"],
                "title": source["title"],
                "created_at": source["created_at"]
            })
            
        return {
            "total": response["hits"]["total"]["value"],
            "page": page,
            "size": size,
            "documents": documents
        }
    except Exception as e:
        logger.error(f"Error listing documents: {e}")
        # Index might not exist yet if no files uploaded
        return {"total": 0, "page": page, "size": size, "documents": []}


@router.delete("/documents/{document_id}", response_model=DocumentDeleteResponse, summary="Delete Document", description="Delete a document and all its chunks from the index")
async def delete_document(
    document_id: str,
    request: Request,
    x_company_id: str = Header(..., alias="X-Company-ID")
):
    company_id = getattr(request.state, "company_id", None)
    if not company_id:
        raise HTTPException(status_code=400, detail="Company ID missing")

    index_name = get_index_name(company_id)
    client = ESClient.get_client()

    try:
        response = await client.delete_by_query(
            index=index_name,
            body={
                "query": {
                    "term": {"document_id": document_id}
                }
            }
        )
        deleted = response.get("deleted", 0)
        if deleted == 0:
            raise HTTPException(status_code=404, detail=f"Document {document_id} not found in index")

        logger.info(f"Deleted {deleted} chunks for document {document_id} from index {index_name}")
        return {
            "document_id": document_id,
            "deleted_chunks": deleted,
            "status": "deleted"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting document {document_id}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")
