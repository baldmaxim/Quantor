"""Реализация ObjectStorage поверх S3-совместимого API (MinIO локально)."""

from __future__ import annotations

import hashlib
import tempfile
from collections.abc import AsyncIterator, Mapping
from functools import lru_cache
from types import TracebackType
from typing import IO, TYPE_CHECKING
from urllib.parse import quote

import aioboto3
from aiobotocore.config import AioConfig
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings, get_settings
from app.storage.base import ObjectNotFoundError, ObjectStat, StorageUnavailableError, StoredObject

if TYPE_CHECKING:
    from aiobotocore.session import ClientCreatorContext
    from types_aiobotocore_s3.client import S3Client

# Кусок, которым файл переливается на диск и оттуда в хранилище.
CHUNK_SIZE = 1024 * 1024
_NOT_FOUND_CODES = frozenset({"404", "NoSuchKey", "NotFound", "NoSuchBucket"})


def _is_not_found(error: ClientError) -> bool:
    code = str(error.response.get("Error", {}).get("Code", ""))
    http_status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return code in _NOT_FOUND_CODES or http_status == 404


def _encode_metadata(
    original_filename: str | None, metadata: Mapping[str, str] | None
) -> dict[str, str]:
    """Метаданные S3 — только ASCII, поэтому кириллические имена кодируются percent-encoding."""
    encoded: dict[str, str] = {}
    if original_filename:
        encoded["original-filename"] = quote(original_filename, safe="")
    for key, value in (metadata or {}).items():
        encoded[key] = quote(value, safe="")
    return encoded


class S3ObjectStorage:
    """S3-хранилище.

    Клиент создаётся на операцию: сессия aioboto3 переиспользуема, клиент — нет.

    Приём потока идёт через временный файл на диске: так память не зависит от размера
    документа, а boto3 получает обычный файловый объект и сам разбивает загрузку на части.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._session = aioboto3.Session()
        self._config = AioConfig(
            signature_version="s3v4",
            s3={"addressing_style": "path" if settings.s3_use_path_style else "auto"},
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=60,
        )

    @property
    def bucket(self) -> str:
        return self._settings.s3_bucket

    def _client(self) -> ClientCreatorContext[S3Client]:
        return self._session.client(
            "s3",
            endpoint_url=self._settings.s3_endpoint_url,
            region_name=self._settings.s3_region,
            aws_access_key_id=self._settings.s3_access_key_id,
            aws_secret_access_key=self._settings.s3_secret_access_key.get_secret_value(),
            config=self._config,
        )

    async def check_available(self) -> None:
        """HEAD по бакету: разом проверяет сеть, креды и существование бакета."""
        try:
            async with self._client() as client:
                await client.head_bucket(Bucket=self.bucket)
        except (ClientError, BotoCoreError) as error:
            raise StorageUnavailableError(str(error)) from error

    async def put_stream(
        self,
        key: str,
        chunks: AsyncIterator[bytes],
        *,
        content_type: str,
        original_filename: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        digest = hashlib.sha256()
        size = 0

        with tempfile.SpooledTemporaryFile(max_size=CHUNK_SIZE * 4) as spool:
            async for chunk in chunks:
                if not chunk:
                    continue
                digest.update(chunk)
                size += len(chunk)
                spool.write(chunk)
            spool.seek(0)
            await self._upload_fileobj(
                spool,
                key,
                content_type=content_type,
                original_filename=original_filename,
                metadata=metadata,
            )

        return StoredObject(key=key, size=size, sha256=digest.hexdigest())

    async def put_bytes(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        original_filename: str | None = None,
        metadata: Mapping[str, str] | None = None,
    ) -> StoredObject:
        try:
            async with self._client() as client:
                await client.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=data,
                    ContentType=content_type,
                    Metadata=_encode_metadata(original_filename, metadata),
                )
        except (ClientError, BotoCoreError) as error:
            raise StorageUnavailableError(str(error)) from error

        return StoredObject(key=key, size=len(data), sha256=hashlib.sha256(data).hexdigest())

    async def _upload_fileobj(
        self,
        fileobj: IO[bytes],
        key: str,
        *,
        content_type: str,
        original_filename: str | None,
        metadata: Mapping[str, str] | None,
    ) -> None:
        # Конфигурация переноса берётся по умолчанию: aioboto3 сам переходит на multipart
        # для крупных файлов, а память ограничена тем, что источник — файл на диске.
        try:
            async with self._client() as client:
                await client.upload_fileobj(
                    fileobj,
                    self.bucket,
                    key,
                    ExtraArgs={
                        "ContentType": content_type,
                        "Metadata": _encode_metadata(original_filename, metadata),
                    },
                )
        except (ClientError, BotoCoreError) as error:
            raise StorageUnavailableError(str(error)) from error

    async def iter_stream(self, key: str, *, chunk_size: int = CHUNK_SIZE) -> AsyncIterator[bytes]:
        try:
            async with self._client() as client:
                response = await client.get_object(Bucket=self.bucket, Key=key)
                async with response["Body"] as body:
                    while True:
                        chunk = await body.read(chunk_size)
                        if not chunk:
                            break
                        yield chunk
        except ClientError as error:
            if _is_not_found(error):
                raise ObjectNotFoundError(key) from error
            raise StorageUnavailableError(str(error)) from error
        except BotoCoreError as error:
            raise StorageUnavailableError(str(error)) from error

    async def stat(self, key: str) -> ObjectStat:
        try:
            async with self._client() as client:
                head = await client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as error:
            if _is_not_found(error):
                raise ObjectNotFoundError(key) from error
            raise StorageUnavailableError(str(error)) from error
        except BotoCoreError as error:
            raise StorageUnavailableError(str(error)) from error

        return ObjectStat(
            key=key,
            size=int(head.get("ContentLength", 0)),
            content_type=head.get("ContentType"),
            last_modified=head.get("LastModified"),
            metadata=dict(head.get("Metadata", {})),
        )

    async def delete(self, key: str) -> None:
        try:
            async with self._client() as client:
                await client.delete_object(Bucket=self.bucket, Key=key)
        except (ClientError, BotoCoreError) as error:
            raise StorageUnavailableError(str(error)) from error

    async def presigned_get_url(
        self, key: str, *, expires_in: int, download_filename: str | None = None
    ) -> str:
        params: dict[str, str] = {"Bucket": self.bucket, "Key": key}
        if download_filename:
            # RFC 5987: имя файла с кириллицей должно доехать до браузера читаемым.
            encoded = quote(download_filename, safe="")
            params["ResponseContentDisposition"] = f"inline; filename*=UTF-8''{encoded}"
        try:
            async with self._client() as client:
                url: str = await client.generate_presigned_url(
                    "get_object", Params=params, ExpiresIn=expires_in
                )
        except (ClientError, BotoCoreError) as error:
            raise StorageUnavailableError(str(error)) from error
        return url

    async def __aenter__(self) -> S3ObjectStorage:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        return None


@lru_cache(maxsize=1)
def get_object_storage() -> S3ObjectStorage:
    return S3ObjectStorage(get_settings())
