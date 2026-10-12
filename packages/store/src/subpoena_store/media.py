"""Witness photos (receipts). Keys are ``{workspace_id}/{media_id}`` so a workspace can only
ever address its own objects; the bucket has no public access and a short lifecycle."""

from __future__ import annotations

import asyncio
from typing import Protocol


class MediaStore(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> tuple[bytes, str] | None:
        """``(bytes, content_type)`` or ``None`` if the object does not exist."""
        ...


class MemoryMediaStore:
    def __init__(self) -> None:
        self._objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        self._objects[key] = (data, content_type)

    async def get(self, key: str) -> tuple[bytes, str] | None:
        return self._objects.get(key)


class GcsMediaStore:
    def __init__(self, bucket: str, project: str | None = None) -> None:
        from google.cloud.storage import Client

        self._bucket = Client(project=project).bucket(bucket)

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        blob = self._bucket.blob(key)
        await asyncio.to_thread(blob.upload_from_string, data, content_type=content_type)

    async def get(self, key: str) -> tuple[bytes, str] | None:
        blob = await asyncio.to_thread(self._bucket.get_blob, key)  # loads content_type too
        if blob is None:
            return None
        data = await asyncio.to_thread(blob.download_as_bytes)
        return data, blob.content_type or "application/octet-stream"


def build_media_store(kind: str, bucket: str | None, project: str | None) -> MediaStore:
    if kind == "gcs":
        if not bucket:
            raise ValueError("SUBPOENA_MEDIA_BUCKET is required for the gcs media store")
        return GcsMediaStore(bucket, project)
    return MemoryMediaStore()
