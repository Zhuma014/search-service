from fastapi import APIRouter, Request, HTTPException, Header, Query, BackgroundTasks
from app.services.sync_service import sync_documents
from pydantic import BaseModel
from typing import List, Optional, Union
import logging

# ── Response Models ────────────────────────────────────
class SyncError(BaseModel):
    document_id: Optional[str] = None
    error: str

class SyncResponse(BaseModel):
    status: str
    message: str

class SingleSyncResponse(BaseModel):
    status: str
    message: str
    synced_count: int
    errors: List[dict] = []

router = APIRouter()
logger = logging.getLogger(__name__)

# Глобальное состояние синхронизации
is_syncing = False

async def run_sync_in_background(company_id: str, document_id: str):
    global is_syncing
    try:
        logger.info(f"Background sync started for company: {company_id}, doc: {document_id}")
        await sync_documents(company_id, document_id)
        logger.info("Background sync completed successfully")
    except Exception as e:
        logger.error(f"Background sync failed: {e}")
    finally:
        is_syncing = False

@router.post("/upload", response_model=Union[SyncResponse, SingleSyncResponse], summary="Sync Documents", description="Synchronize documents from PostgreSQL/MinIO to Elasticsearch")
async def trigger_sync(
    background_tasks: BackgroundTasks,
    request: Request,
    document_id: str = Query(None),
    x_company_id: str = Header(None, alias="X-Company-ID")
):
    """
    Triggers a synchronization of documents from Postgres/MinIO to Elasticsearch.
    Returns immediately and runs the sync in the background.
    """
    global is_syncing
    
    if is_syncing:
        return {
            "status": "already_running",
            "message": "Synchronization is already in progress. Please Wait."
        }
    
    company_id = getattr(request.state, "company_id", None)
    
    if not company_id and not document_id:
        raise HTTPException(status_code=400, detail="Either X-Company-ID header or document_id query parameter must be provided")
    
    is_syncing = True
    
    if document_id:
        try:
            logger.info(f"Synchronous sync started for doc: {document_id}")
            synced_count, errors = await sync_documents(company_id, document_id)
            is_syncing = False
            
            if errors:
                return {
                    "status": "partial_success" if synced_count > 0 else "failed",
                    "message": f"Synchronization for document {document_id} completed with errors.",
                    "synced_count": synced_count,
                    "errors": errors
                }
            
            return {
                "status": "success",
                "message": f"Document {document_id} successfully synchronized.",
                "synced_count": synced_count,
                "errors": []
            }
        except Exception as e:
            is_syncing = False
            logger.error(f"Synchronous sync failed: {e}")
            raise HTTPException(status_code=500, detail=f"Sync failed: {str(e)}")
    
    background_tasks.add_task(run_sync_in_background, company_id, document_id)
    
    return {
        "status": "started",
        "message": "Full synchronization started in background. Monitor logs for progress."
    }
