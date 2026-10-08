"""S3-compatible blob storage for tapes: content-addressed blobs (deduped
by hash, Milestone 1's data model) plus the per-run manifest and step
records that give a tape its order.

Points at SeaweedFS locally (see infra/k8s/local/base/object-storage.yaml
and DECISIONS.md - MinIO's own images were withdrawn by the vendor), real
AWS S3 in production. Both speak the same S3 API, so this is the same
client either way.
"""

from __future__ import annotations

import json
import os
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from pg_sdk.hashing import content_hash


class BlobStore:
    def __init__(
        self,
        bucket: str | None = None,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str | None = None,
    ) -> None:
        self.bucket = bucket or os.environ.get("PG_S3_BUCKET", "proving-ground-tapes")
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or os.environ.get("PG_S3_ENDPOINT_URL", "http://127.0.0.1:29001"),
            aws_access_key_id=access_key or os.environ.get("PG_S3_ACCESS_KEY_ID", "proving_ground"),
            aws_secret_access_key=secret_key
            or os.environ.get("PG_S3_SECRET_ACCESS_KEY", "proving-ground-local-dev"),
            region_name=region or os.environ.get("PG_S3_REGION", "us-east-1"),
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    # --- content-addressed blobs -----------------------------------------

    def _blob_key(self, digest: str) -> str:
        return f"blobs/sha256/{digest[:2]}/{digest}.json"

    def put_blob(self, data: bytes) -> str:
        """Uploads `data` if a blob with this hash doesn't already exist
        (real dedup, not just a naming convention: a HEAD check skips the
        PUT entirely on a cache hit). Returns the hash."""
        digest = content_hash(data)
        key = self._blob_key(digest)
        if not self._exists(key):
            self._client.put_object(Bucket=self.bucket, Key=key, Body=data)
        return digest

    def get_blob(self, digest: str) -> bytes:
        resp = self._client.get_object(Bucket=self.bucket, Key=self._blob_key(digest))
        return resp["Body"].read()

    def blob_exists(self, digest: str) -> bool:
        return self._exists(self._blob_key(digest))

    # --- per-run steps and manifest ---------------------------------------

    def put_step(self, run_id: str, seq: int, step: dict[str, Any]) -> None:
        key = f"runs/{run_id}/steps/{seq:05d}.json"
        self._client.put_object(
            Bucket=self.bucket, Key=key, Body=json.dumps(step, sort_keys=True).encode("utf-8")
        )

    def get_step(self, run_id: str, seq: int) -> dict[str, Any]:
        key = f"runs/{run_id}/steps/{seq:05d}.json"
        resp = self._client.get_object(Bucket=self.bucket, Key=key)
        return json.loads(resp["Body"].read())

    def put_manifest(self, run_id: str, manifest: dict[str, Any]) -> None:
        key = f"runs/{run_id}/manifest.json"
        self._client.put_object(
            Bucket=self.bucket, Key=key, Body=json.dumps(manifest, sort_keys=True).encode("utf-8")
        )

    def get_manifest(self, run_id: str) -> dict[str, Any]:
        key = f"runs/{run_id}/manifest.json"
        resp = self._client.get_object(Bucket=self.bucket, Key=key)
        return json.loads(resp["Body"].read())

    def _exists(self, key: str) -> bool:
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                return False
            raise
