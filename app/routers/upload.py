from fastapi import APIRouter, Request, HTTPException, Header, Query
from app.services.sync_service import sync_documents
from pydantic import BaseModel
from typing import List, Optional
import logging

# ── Response Models ────────────────────────────────────
class SyncError(BaseModel):
    document_id: Optional[str] = None
    error: str

class SyncResponse(BaseModel):
    status: str
    synced_count: int
    errors_count: int
    errors: List[SyncError] = []

router = APIRouter()
logger = logging.getLogger(__name__)

@router.post("/upload", response_model=SyncResponse, summary="Sync Documents", description="Synchronize documents from PostgreSQL/MinIO to Elasticsearch")
async def trigger_sync(
    request: Request,
    document_id: str = Query(None),
    x_company_id: str = Header(None, alias="X-Company-ID")
):
    """
    Triggers a synchronization of documents from Postgres/MinIO to Elasticsearch.
    Can sync a specific document if document_id is provided.
    If document_id is provided, X-Company-ID is optional (it will be fetched from DB).
    """
    company_id = getattr(request.state, "company_id", None)
    
    if not company_id and not document_id:
        raise HTTPException(status_code=400, detail="Either X-Company-ID header or document_id query parameter must be provided")
    
    # Use company_id provided in header
    try:
        synced, errors = await sync_documents(company_id, document_id)
        return {
            "status": "completed",
            "synced_count": synced,
            "errors_count": len(errors),
            "errors": errors if errors else []
        }
    except Exception as e:
        logger.error(f"Error during sync: {e}")
        raise HTTPException(status_code=500, detail=str(e))
