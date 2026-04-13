from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.elasticsearch.client import ESClient
from app.middleware.tenant import TenantMiddleware
from app.routers import search, documents, ask, upload, generate, knowledge
from app.db.postgres_client import postgres_client
from app.storage.minio_client import minio_client
from config import settings
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional, Dict, Any
import logging

# ── Response Models ────────────────────────────────────
class ServiceStatus(BaseModel):
    status: str
    version: Optional[str] = None
    error: Optional[str] = None

class HealthCheckResponse(BaseModel):
    service: str
    elasticsearch: ServiceStatus
    postgresql: ServiceStatus
    minio: ServiceStatus

logging.basicConfig(level=settings.LOG_LEVEL.upper())
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Test Elasticsearch
    client = ESClient.get_client()
    try:
        info = await client.info()
        logger.info(f"✓ Connected to Elasticsearch: {info['version']['number']}")
    except Exception as e:
        logger.warning(f"⚠ Failed to connect to Elasticsearch: {e}")
    
    # Test PostgreSQL (non-blocking)
    try:
        factory = postgres_client.get_session_factory()
        if factory:
            async with factory() as session:
                await session.execute(text("SELECT 1"))
                logger.info("✓ Connected to PostgreSQL")
        else:
            logger.warning("⚠ PostgreSQL: DATABASE_URL not configured")
    except Exception as e:
        logger.warning(f"⚠ Failed to connect to PostgreSQL: {type(e).__name__}. Check DATABASE_URL and network connectivity to {settings.DATABASE_URL.split('@')[-1] if settings.DATABASE_URL else 'unknown'}")
    
    # Test MinIO (non-blocking)
    try:
        minio = minio_client.get_client()
        # Just list buckets to test connection (doesn't require specific bucket access)
        minio.list_buckets()
        logger.info(f"✓ Connected to MinIO (bucket: {settings.MINIO_BUCKET}, endpoint: {settings.MINIO_ENDPOINT})")
    except Exception as e:
        logger.warning(f"⚠ Failed to connect to MinIO: {type(e).__name__}")
    
    yield
    
    await ESClient.close()
    logger.info("Closed Elasticsearch connection")

app = FastAPI(
    title="Search Service",
    description="Microservice for lexical search and RAG via Elasticsearch and Gemini",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(TenantMiddleware)

@app.get("/health", response_model=HealthCheckResponse, summary="Service Health Check", description="Check connection to all services")
async def health_check():
    """Check connection to all services: Elasticsearch, PostgreSQL, MinIO"""
    result = {
        "service": "search-service",
        "elasticsearch": None,
        "postgresql": None,
        "minio": None,
    }
    
    # Check Elasticsearch
    try:
        client = ESClient.get_client()
        info = await client.info()
        result["elasticsearch"] = {
            "status": "connected",
            "version": info['version']['number']
        }
    except Exception as e:
        result["elasticsearch"] = {"status": "failed", "error": str(e)}
    
    # Check PostgreSQL
    try:
        factory = postgres_client.get_session_factory()
        if factory:
            async with factory() as session:
                await session.execute(text("SELECT 1"))
                result["postgresql"] = {"status": "connected"}
        else:
            result["postgresql"] = {
                "status": "failed",
                "error": "DATABASE_URL not configured"
            }
    except Exception as e:
        result["postgresql"] = {"status": "failed", "error": f"{type(e).__name__}: {str(e)}"}
    
    # Check MinIO
    try:
        minio = minio_client.get_client()
        minio.list_buckets()
        result["minio"] = {
            "status": "connected",
            "bucket": settings.MINIO_BUCKET,
            "endpoint": settings.MINIO_ENDPOINT
        }
    except Exception as e:
        result["minio"] = {"status": "failed", "error": f"{type(e).__name__}: {str(e)}"}
    
    return result

# Включаем роутеры с префиксом /ai/api
app.include_router(search.router, prefix="/ai/api", tags=["search"])
app.include_router(upload.router, prefix="/ai/api", tags=["upload to ES"])
app.include_router(documents.router, prefix="/ai/api", tags=["documents in ES"])
app.include_router(ask.router, prefix="/ai/api", tags=["ask"])
app.include_router(generate.router, prefix="/ai/api", tags=["generate"])
app.include_router(knowledge.router, prefix="/ai/api", tags=["knowledge"])