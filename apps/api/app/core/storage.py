"""Object storage behind a small interface (S3 API; MinIO in development).

Why boto3 and not aioboto3: the hot path is pre-signing, which is pure
local HMAC work with no I/O, so an async client buys nothing there. The few
real network calls (HEAD, GET and DELETE when verifying an upload, PUTs from
the media worker) run in a thread via `asyncio.to_thread`, and the Celery
worker gets the same code. aiobotocore pins exact botocore versions, which
makes it a frequent source of resolver conflicts for little gain.

Two clients are kept. `_client` talks to S3_ENDPOINT for server-side work.
`_signer` never makes a request: it only signs URLs for S3_PUBLIC_ENDPOINT,
because a SigV4 signature covers the Host header and the browser must send
exactly the host that was signed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from typing import Annotated, Any, Protocol

from boto3.session import Session as Boto3Session
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import Depends

from app.core.config import Settings, get_settings

_DELETE_BATCH = 1000  # S3 DeleteObjects limit
_MISSING_CODES = {"404", "NoSuchKey", "NotFound"}


class StorageError(Exception):
    """Storage is unreachable or refused a request."""


class ObjectTooLarge(StorageError):
    """An object is bigger than the caller is willing to read."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    size: int
    content_type: str | None


class ObjectStorage(Protocol):
    def presign_put(
        self, key: str, *, content_type: str, content_length: int, expires_in: int
    ) -> str: ...

    def presign_get(self, key: str, *, expires_in: int) -> str: ...

    async def head(self, key: str) -> StoredObject | None: ...

    async def read(self, key: str, *, max_bytes: int) -> bytes: ...

    async def write(self, key: str, data: bytes, *, content_type: str) -> None: ...

    async def delete(self, keys: Iterable[str]) -> None: ...


def _client(settings: Settings, endpoint: str) -> Any:
    return Boto3Session().client(
        "s3",
        endpoint_url=endpoint,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key.get_secret_value(),
        aws_secret_access_key=settings.s3_secret_key.get_secret_value(),
        config=Config(
            signature_version="s3v4",
            # Path-style keeps the bucket out of the hostname, which MinIO
            # and the browser's CORS origin checks both need in development.
            s3={"addressing_style": "path"},
            connect_timeout=3,
            read_timeout=15,
            retries={"max_attempts": 3, "mode": "standard"},
        ),
    )


def _is_missing(exc: ClientError) -> bool:
    error = exc.response.get("Error", {})
    return str(error.get("Code")) in _MISSING_CODES


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self._client = _client(settings, settings.s3_endpoint)
        self._signer = _client(settings, settings.s3_presign_endpoint)

    # --- signing (no I/O) --------------------------------------------------------

    def presign_put(
        self, key: str, *, content_type: str, content_length: int, expires_in: int
    ) -> str:
        # Content-Type and Content-Length are part of the signature, so storage
        # itself rejects a PUT with a different type or a different size.
        # Browsers send Content-Length on their own; only Content-Type has to
        # be passed back to the client as a header to set.
        return self._signer.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ContentType": content_type,
                "ContentLength": content_length,
            },
            ExpiresIn=expires_in,
        )

    def presign_get(self, key: str, *, expires_in: int) -> str:
        return self._signer.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_in
        )

    # --- server-side calls ---------------------------------------------------------

    def _head(self, key: str) -> StoredObject | None:
        try:
            response = self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if _is_missing(exc):
                return None
            raise StorageError(str(exc)) from exc
        except BotoCoreError as exc:
            raise StorageError(str(exc)) from exc
        return StoredObject(
            size=int(response["ContentLength"]), content_type=response.get("ContentType")
        )

    def _read(self, key: str, max_bytes: int) -> bytes:
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(str(exc)) from exc
        body = response["Body"]
        try:
            if int(response["ContentLength"]) > max_bytes:
                raise ObjectTooLarge(key)
            data = body.read(max_bytes + 1)
        finally:
            body.close()
        if len(data) > max_bytes:  # pragma: no cover - ContentLength lied
            raise ObjectTooLarge(key)
        return data

    def _write(self, key: str, data: bytes, content_type: str) -> None:
        try:
            self._client.put_object(
                Bucket=self.bucket, Key=key, Body=data, ContentType=content_type
            )
        except (ClientError, BotoCoreError) as exc:
            raise StorageError(str(exc)) from exc

    def _delete(self, keys: list[str]) -> None:
        for start in range(0, len(keys), _DELETE_BATCH):
            batch = keys[start : start + _DELETE_BATCH]
            try:
                response = self._client.delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True},
                )
            except (ClientError, BotoCoreError) as exc:
                raise StorageError(str(exc)) from exc
            # Deleting a key that doesn't exist is a success in S3, so any
            # reported error is a real one.
            if response.get("Errors"):
                raise StorageError(f"could not delete {len(response['Errors'])} object(s)")

    async def head(self, key: str) -> StoredObject | None:
        return await asyncio.to_thread(self._head, key)

    async def read(self, key: str, *, max_bytes: int) -> bytes:
        return await asyncio.to_thread(self._read, key, max_bytes)

    async def write(self, key: str, data: bytes, *, content_type: str) -> None:
        await asyncio.to_thread(self._write, key, data, content_type)

    async def delete(self, keys: Iterable[str]) -> None:
        unique = sorted(set(keys))
        if unique:
            await asyncio.to_thread(self._delete, unique)


@lru_cache
def get_storage() -> ObjectStorage:
    return S3Storage(get_settings())


Storage = Annotated[ObjectStorage, Depends(get_storage)]
