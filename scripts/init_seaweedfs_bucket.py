"""One-shot script: create the S3 bucket on SeaweedFS for local dev.

Usage (after `docker compose up -d`):
    python scripts/init_seaweedfs_bucket.py
"""

from __future__ import annotations

import asyncio

from aiobotocore.session import get_session
from botocore.exceptions import ClientError

from app.core.config import settings


async def ensure_bucket() -> None:
    sess = get_session()
    async with sess.create_client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
        region_name=settings.S3_REGION,
    ) as s3:
        try:
            await s3.head_bucket(Bucket=settings.S3_BUCKET)
            print(f"[ok] bucket already exists: {settings.S3_BUCKET}")
            return
        except ClientError as e:
            if e.response["Error"]["Code"] not in {"404", "NoSuchBucket"}:
                raise

        await s3.create_bucket(Bucket=settings.S3_BUCKET)
        print(f"[created] bucket: {settings.S3_BUCKET}")


if __name__ == "__main__":
    asyncio.run(ensure_bucket())
