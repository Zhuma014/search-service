from fastapi import APIRouter, Request
from app.services.incremental_sync import run_incremental_sync
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post(
    "/sync/incremental",
    summary="Trigger Incremental Sync",
    description="Manually trigger the hourly incremental sync (finds new docs and newly-assigned task docs across all companies).",
)
async def trigger_incremental_sync(request: Request):
    logger.info("Manual incremental sync triggered")
    result = await run_incremental_sync()
    return {
        "status": "completed",
        "synced_count": result["synced"],
        "error_count":  result["errors"],
    }
