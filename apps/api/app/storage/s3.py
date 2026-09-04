"""Реализация ObjectStorage поверх S3-совместимого API (MinIO локально)."""

from __future__ import annotations

from functools import lru_cache

import aioboto3
from aiobotocore.config import AioConfig

from app.core.config import Settings, get_settings


class S3ObjectStorage:
    """S3-хранилище.

    Клиент создаётся на операцию: aioboto3-сессия переиспользуема, клиент — нет.
    Потоковая загрузка, presigned URL и удаление появятся в промте 03 вместе с потребителями.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session = aioboto3.Session()
        self._config = AioConfig(
            signature_version="s3v4",
            s3={"addressing_style": "path" if settings.s3_use_path_style else "auto"},
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=30,
        )

    @property
    def bucket(self) -> str:
        return self._settings.s3_bucket

    async def check_available(self) -> None:
        """HEAD по бакету: разом проверяет сетевую доступность, креды и существование бакета."""
        async with self._session.client(
            "s3",
            endpoint_url=self._settings.s3_endpoint_url,
            region_name=self._settings.s3_region,
            aws_access_key_id=self._settings.s3_access_key_id,
            aws_secret_access_key=self._settings.s3_secret_access_key.get_secret_value(),
            config=self._config,
        ) as client:
            await client.head_bucket(Bucket=self.bucket)


@lru_cache(maxsize=1)
def get_object_storage() -> S3ObjectStorage:
    return S3ObjectStorage(get_settings())
