from elasticsearch import AsyncElasticsearch
from config import settings

class ESClient:
    _instance = None

    @classmethod
    def get_client(cls) -> AsyncElasticsearch:
        if cls._instance is None:
            cls._instance = AsyncElasticsearch(
                settings.ES_URL,
                retry_on_timeout=True,
                max_retries=10
            )
        return cls._instance

    @classmethod
    async def close(cls):
        if cls._instance:
            await cls._instance.close()
            cls._instance = None

def get_index_name(company_id: str) -> str:
    """
    Returns the index name for a specific company.
    Index name format: {company_id}_documents
    """
    # Sanitize company_id to avoid injection and comply with ES index naming rules
    sanitized_id = "".join(c for c in company_id if c.isalnum() or c in "-_").lower()
    return f"{sanitized_id}_documents"
