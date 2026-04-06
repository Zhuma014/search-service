from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.elasticsearch.client import ESClient
from app.middleware.tenant import TenantMiddleware
from app.routers import search, documents, ask, upload, generate
from config import settings
import logging

logging.basicConfig(level=settings.LOG_LEVEL.upper())
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    client = ESClient.get_client()
    try:
        info = await client.info()
        logger.info(f"Connected to Elasticsearch: {info['version']['number']}")
    except Exception as e:
        logger.error(f"Failed to connect to Elasticsearch: {e}")
    
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

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "search-service"}

app.include_router(search.router, tags=["search"])
app.include_router(upload.router, tags=["upload to ES"])
app.include_router(documents.router, tags=["documents in ES"])
app.include_router(ask.router, tags=["ask"])
app.include_router(generate.router, tags=["generate"])
