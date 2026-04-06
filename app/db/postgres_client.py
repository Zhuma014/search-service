from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
from config import settings
import logging

logger = logging.getLogger(__name__)

class PostgresClient:
    _engine = None
    _session_factory = None

    @classmethod
    def get_engine(cls):
        if cls._engine is None:
            if not settings.DATABASE_URL:
                logger.error("DATABASE_URL is not set in environment")
                return None
            cls._engine = create_async_engine(settings.DATABASE_URL, echo=False)
        return cls._engine

    @classmethod
    def get_session_factory(cls):
        if cls._session_factory is None:
            engine = cls.get_engine()
            if engine:
                cls._session_factory = sessionmaker(
                    engine, class_=AsyncSession, expire_on_commit=False
                )
        return cls._session_factory

    @classmethod
    async def fetch_documents(cls, table_name: str, limit: int = 100):
        """
        Generic helper to fetch documents. 
        User should provide the table name.
        """
        factory = cls.get_session_factory()
        if not factory:
            return []
            
        async with factory() as session:
            try:
                # We assume a standard structure for now, but allow flexibility
                # The user will need to confirm the exact schema
                query = text(f"SELECT * FROM {table_name} LIMIT :limit")
                result = await session.execute(query, {"limit": limit})
                # Convert results to list of dicts
                return [dict(row._mapping) for row in result.all()]
            except Exception as e:
                logger.error(f"Error fetching from Postgres table {table_name}: {e}")
                return []

postgres_client = PostgresClient()
