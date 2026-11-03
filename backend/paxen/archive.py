"""Raw feed archive: every TfL response, gzip-compressed, outside the database.

The database keeps a lean, sampled copy for training; this archive keeps everything, so ground-truth
inference can be rebuilt from the originals if we ever find another bug.

PAXEN_ARCHIVE_URL:
  ""                       disabled
  file:///data/archive     local folder (e.g. a Railway volume)
  s3://bucket/prefix       S3-compatible storage (Cloudflare R2, AWS S3, Backblaze B2...). Credentials from
                           AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY; for R2 also set AWS_ENDPOINT_URL to
                           https://<account-id>.r2.cloudflarestorage.com
Objects: raw/<source>/<YYYY-MM-DD>/<HH>/<name>-<HHMMSS>.json.gz (UTC)
"""
from __future__ import annotations

import gzip
import logging
import os
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from .timeutil import aware

log = logging.getLogger("paxen.archive")


def object_key(source: str, name: str, when: datetime) -> str:
    from datetime import timezone

    t = aware(when).astimezone(timezone.utc)
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")[:80]
    return f"raw/{source}/{t:%Y-%m-%d}/{t:%H}/{safe}-{t:%H%M%S}.json.gz"


class LocalArchive:
    def __init__(self, root: str):
        self.root = Path(root)

    def put(self, key: str, data: bytes) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return f"file://{path}"


class S3Archive:
    def __init__(self, bucket: str, prefix: str, client=None):
        if client is None:
            import boto3  # optional dependency, only needed for s3:// archives

            client = boto3.client("s3", endpoint_url=os.getenv("AWS_ENDPOINT_URL") or None,
                                  region_name=os.getenv("AWS_REGION", "auto"))
        self.client, self.bucket, self.prefix = client, bucket, prefix.strip("/")

    def put(self, key: str, data: bytes) -> str:
        full = f"{self.prefix}/{key}" if self.prefix else key
        self.client.put_object(Bucket=self.bucket, Key=full, Body=data, ContentType="application/json",
                               ContentEncoding="gzip")
        return f"s3://{self.bucket}/{full}"


@lru_cache(maxsize=1)
def get_archive():
    url = os.getenv("PAXEN_ARCHIVE_URL", "").strip()
    if not url:
        return None
    u = urlparse(url)
    if u.scheme == "file":
        return LocalArchive(u.path)
    if u.scheme == "s3":
        return S3Archive(u.netloc, u.path)
    raise ValueError(f"Unsupported PAXEN_ARCHIVE_URL scheme: {u.scheme}")


def archive_raw(source: str, name: str, when: datetime, raw: str | bytes, archive=None) -> str | None:
    """Compress and store one raw response. Never raises: a storage outage must not stop recording."""
    archive = archive if archive is not None else get_archive()
    if archive is None or not raw:
        return None
    try:
        data = raw if isinstance(raw, bytes) else raw.encode()
        return archive.put(object_key(source, name, when), gzip.compress(data, compresslevel=6))
    except Exception as e:
        log.warning("archive write failed (%s): %s", name, e)
        return None
