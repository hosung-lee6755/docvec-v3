import logging
from io import BytesIO

from minio import Minio
from minio.error import S3Error

from app.core.config import settings

logger = logging.getLogger(__name__)


class StorageService:
    def __init__(self) -> None:
        self._client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )
        # Presigned URLs embed the endpoint host into the signature, so they must be
        # generated against the browser-reachable host, not the internal Docker service name.
        self._public_client = Minio(
            settings.minio_public_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_public_secure,
            # Skip auto region lookup: it connects to the endpoint host, which for the
            # public client is only reachable from outside the Docker network.
            region="us-east-1",
        )

    def init_buckets(self) -> None:
        for bucket in [settings.minio_bucket_originals, settings.minio_bucket_artifacts]:
            if not self._client.bucket_exists(bucket):
                self._client.make_bucket(bucket)

    def upload_file(
        self, bucket: str, key: str, data: bytes, content_type: str
    ) -> str:
        self._client.put_object(
            bucket,
            key,
            BytesIO(data),
            len(data),
            content_type=content_type,
        )
        return key

    def download_file(self, bucket: str, key: str) -> bytes:
        response = self._client.get_object(bucket, key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def get_presigned_url(self, bucket: str, key: str, expires_seconds: int = 3600) -> str:
        from datetime import timedelta
        from urllib.parse import urlsplit

        url = self._public_client.presigned_get_object(
            bucket, key, expires=timedelta(seconds=expires_seconds)
        )
        if not settings.minio_relative_urls:
            return url
        # 서명은 minio_public_endpoint 호스트로 계산되지만, URL 에서는 호스트를 뗀다. 브라우저가 접속한
        # 출처로 요청하면 Caddy 가 Host 를 서명 호스트로 되돌려 MinIO 가 서명을 검증한다.
        parts = urlsplit(url)
        return f"{parts.path}?{parts.query}" if parts.query else parts.path

    def delete_file(self, bucket: str, key: str) -> None:
        try:
            self._client.remove_object(bucket, key)
        except S3Error:
            # 삭제는 best-effort(없는 객체 포함)지만 실제 스토리지 장애를 숨기지 않도록 기록한다.
            logger.warning("객체 삭제 실패: %s/%s", bucket, key, exc_info=True)


storage_service = StorageService()
