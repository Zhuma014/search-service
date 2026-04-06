from minio import Minio
from config import settings
import io
import logging

logger = logging.getLogger(__name__)

class MinioClient:
    _instance = None

    @classmethod
    def get_client(cls):
        if cls._instance is None:
            cls._instance = Minio(
                settings.MINIO_ENDPOINT,
                access_key=settings.MINIO_ACCESS_KEY,
                secret_key=settings.MINIO_SECRET_KEY,
                secure=settings.MINIO_SECURE
            )
        return cls._instance

    @classmethod
    def download_file(cls, minio_path: str, bucket_name: str = None) -> bytes:
        client = cls.get_client()
        bucket = bucket_name or settings.MINIO_BUCKET
        try:
            response = client.get_object(bucket, minio_path)
            data = response.read()
            response.close()
            response.release_conn()
            return data
        except Exception as e:
            logger.error(f"Error downloading file {minio_path} from bucket {bucket}: {e}")
            raise

minio_client = MinioClient()
