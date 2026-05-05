"""Async S3 / SeaweedFS client wrapper.

Provides a small set of helpers tailored to the hybrid-storage strategy
(see backend design doc §3.3):
    - ``put_object``        : upload arbitrary bytes (raw tool outputs, memory.md).
    - ``append_jsonl``      : append a single JSON line to ``messages.jsonl``.
    - ``get_object``        : full read for cache-rebuild on Redis miss.
    - ``presigned_get_url`` : generate a short-lived URL for the frontend.

The client is a singleton ``AioBaseClient``; aiobotocore requires its
``__aenter__`` / ``__aexit__`` to be driven manually if we want to keep it
across requests, so we manage the lifecycle through FastAPI lifespan.
"""

from __future__ import annotations

import json
from typing import Any

from aiobotocore.session import get_session
from botocore.exceptions import ClientError

from app.core.config import settings


class S3Storage:
    """Thin async S3 wrapper bound to the project's bucket."""

    def __init__(self) -> None:
        self._session = get_session()
        self._cm: Any = None
        self._client: Any = None

    async def start(self) -> None:
        if self._client is not None:
            return
        self._cm = self._session.create_client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
            region_name=settings.S3_REGION,
        )
        self._client = await self._cm.__aenter__()

    async def stop(self) -> None:
        if self._cm is not None:
            await self._cm.__aexit__(None, None, None)
            self._cm = None
            self._client = None

    @property
    def client(self) -> Any:
        if self._client is None:
            raise RuntimeError("S3Storage not started; call start() first")
        return self._client

    @property
    def bucket(self) -> str:
        return settings.S3_BUCKET

    # --- primitive ops -------------------------------------------------

    async def put_object(
        self, key: str, body: bytes | str, content_type: str = "application/octet-stream"
    ) -> None:
        if isinstance(body, str):
            body = body.encode("utf-8")
        await self.client.put_object(
            Bucket=self.bucket, Key=key, Body=body, ContentType=content_type
        )

    async def get_object(self, key: str) -> bytes | None:
        try:
            resp = await self.client.get_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            if e.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                return None
            raise
        async with resp["Body"] as stream:
            return await stream.read()

    async def object_exists(self, key: str) -> bool:
        try:
            await self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as e:
            if e.response["Error"]["Code"] in {"404", "NoSuchKey"}:
                return False
            raise

    async def presigned_get_url(self, key: str, expires_in: int = 600) -> str:
        return await self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    async def delete_object(self, key: str) -> None:
        """Delete a single object.  Silently ignores missing keys."""
        try:
            await self.client.delete_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            if e.response["Error"]["Code"] not in {"NoSuchKey", "404"}:
                raise

    # --- jsonl helpers (messages append-only log) ----------------------

    async def append_jsonl(self, key: str, record: dict[str, Any]) -> None:
        """Append a JSON record as a new line in the given key.

        SeaweedFS S3 doesn't support real append; we read-modify-write.
        For Phase 2 traffic this is acceptable; later we can migrate to
        SeaweedFS Filer's native append API.
        """
        existing = await self.get_object(key) or b""
        line = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        await self.put_object(key, existing + line, content_type="application/x-ndjson")

    async def read_jsonl(self, key: str) -> list[dict[str, Any]]:
        raw = await self.get_object(key)
        if not raw:
            return []
        out: list[dict[str, Any]] = []
        for line in raw.decode("utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
        return out


# Singleton — managed by FastAPI lifespan.
s3_storage = S3Storage()


# --- key builders --------------------------------------------------------

def session_prefix(session_id: str) -> str:
    return f"sessions/{session_id}"


def messages_key(session_id: str) -> str:
    return f"{session_prefix(session_id)}/messages.jsonl"


def memory_key(session_id: str) -> str:
    return f"{session_prefix(session_id)}/memory.md"


def raw_output_key(session_id: str, tool_call_id: str) -> str:
    return f"{session_prefix(session_id)}/traces/raw_outputs/{tool_call_id}.json"


def file_key(session_id: str, file_id: str, filename: str) -> str:
    """S3 key for a user-uploaded file."""
    return f"{session_prefix(session_id)}/files/{file_id}/{filename}"


def trace_key(session_id: str, message_id: str) -> str:
    """S3 key for a message's trace JSONL."""
    return f"{session_prefix(session_id)}/traces/{message_id}.jsonl"
