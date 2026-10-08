"""Content addressing: every recorded blob is named by the hash of its own
bytes, so identical requests/responses across runs and across simulations
are stored once (this is also the foundation Milestone 3's model-call
cache and Milestone 4's replay both build on - a tape is nothing more than
an ordered list of these hashes)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> bytes:
    """Stable byte serialization: same logical content always hashes the
    same, regardless of dict key insertion order."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_json(obj: Any) -> tuple[str, bytes]:
    """Returns (hash, canonical_bytes) so a caller can both know the
    address and upload the exact bytes that produced it."""
    payload = canonical_json(obj)
    return content_hash(payload), payload
