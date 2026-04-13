import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    ES_URL: str = "http://localhost:9200"
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    
    # PostgreSQL
    DATABASE_URL: str = ""
    SYNC_TABLE: str = os.getenv("SYNC_TABLE", "document")
    SYNC_LIMIT: int = int(os.getenv("SYNC_LIMIT", "20"))
    
    # MinIO
    MINIO_ENDPOINT: str = os.getenv("MINIO_ENDPOINT", "")
    MINIO_ACCESS_KEY: str = os.getenv("MINIO_ACCESS_KEY", "")
    MINIO_SECRET_KEY: str = os.getenv("MINIO_SECRET_KEY", "")
    MINIO_BUCKET: str = os.getenv("MINIO_BUCKET", "abs-sed-dev")
    MINIO_SECURE: bool = os.getenv("MINIO_SECURE", "true").lower() == "true"
    
    # Service
    SERVICE_PORT: int = 8000
    LOG_LEVEL: str = "info"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()