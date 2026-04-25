from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
from config import settings
import logging

logger = logging.getLogger(__name__)

# Белый список таблиц для защиты от SQL-инъекций
ALLOWED_TABLES = {"document", "users", "metadata"} # Замените на ваши реальные таблицы

class PostgresClient:
    _engine = None
    _session_factory = None

    @classmethod
    def get_engine(cls):
        if cls._engine is None:
            if not settings.DATABASE_URL:
                logger.error("DATABASE_URL is not set in environment")
                return None
            
            logger.info("Initializing PostgreSQL engine with optimized pool...")
            
            # Убрали poolclass=QueuePool. SQLAlchemy сама использует AsyncAdaptedQueuePool.
            cls._engine = create_async_engine(
                settings.DATABASE_URL,
                echo=False,
                pool_size=10,              # ← Основной размер пула
                max_overflow=20,           # ← Дополнительные соединения если нужны
                pool_timeout=10,           # ← Максимум 30 сек ждать соединение
                pool_recycle=300,         # ← Переиспользовать каждый час
                pool_pre_ping=True,        # ← Проверять соединение перед использованием
                connect_args={
                "timeout": 10,         # ← таймаут подключения 10 сек
                "command_timeout": 10, # ← таймаут запроса 10 сек
                        }
            )
            
            logger.info("✓ PostgreSQL engine created with async pool")
        
        return cls._engine

    @classmethod
    def get_session_factory(cls):
        if cls._session_factory is None:
            engine = cls.get_engine()
            if engine:
                # Используем современный async_sessionmaker
                cls._session_factory = async_sessionmaker(
                    engine, 
                    expire_on_commit=False,
                    autoflush=False
                )
        
        return cls._session_factory

    @classmethod
    async def fetch_documents(cls, table_name: str, limit: int = 100):
        """
        Generic helper to fetch documents. 
        """
        # ЗАЩИТА ОТ SQL-ИНЪЕКЦИЙ
        if table_name not in ALLOWED_TABLES:
            logger.error(f"Attempt to access unauthorized or invalid table: {table_name}")
            raise ValueError(f"Invalid table name: {table_name}")

        factory = cls.get_session_factory()
        if not factory:
            return []
            
        async with factory() as session:
            try:
                # Теперь это безопасно, так как table_name прошел проверку
                query = text(f"SELECT * FROM {table_name} LIMIT :limit")
                result = await session.execute(query, {"limit": limit})
                return [dict(row._mapping) for row in result.all()]
            except Exception as e:
                logger.error(f"Error fetching from Postgres table {table_name}: {e}")
                return []

    @classmethod
    async def close(cls):
        """Закрыть все соединения в пуле"""
        if cls._engine is not None:
            await cls._engine.dispose()
            logger.info("✓ PostgreSQL connection pool closed")

postgres_client = PostgresClient()