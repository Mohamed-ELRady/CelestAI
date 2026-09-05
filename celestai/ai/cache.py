"""In-memory exact-response cache for AI calls.

The cache is deliberately conservative: it only reuses a successful response
when every input that can affect the provider response is identical.  Nothing
is persisted to disk, and API keys are represented only by a one-way digest
inside the final request fingerprint.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import OrderedDict
from typing import Any, Iterable

from . import settings

DEFAULT_CACHE_SIZE = 128
MAX_CACHE_SIZE = 1024


def _capacity() -> int:
    raw = os.environ.get("CELESTAI_AI_CACHE_SIZE", str(DEFAULT_CACHE_SIZE)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = DEFAULT_CACHE_SIZE
    return max(0, min(value, MAX_CACHE_SIZE))


def compact_json(value: Any) -> str:
    """Stable, whitespace-free JSON used for schemas and fingerprints."""
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def response_cache_key(
    *,
    kind: str,
    system: str,
    user: str,
    model: str,
    max_tokens: int,
    effort: str = "",
    output_schema: dict[str, Any] | None = None,
    images: Iterable[tuple[str, bytes]] = (),
) -> str:
    """Fingerprint the complete logical request without retaining its secret."""
    config = settings.current()
    credential_scope = (
        hashlib.sha256(config.api_key.encode("utf-8")).hexdigest()
        if config.api_key else ""
    )
    image_fingerprints = [
        {
            "media_type": media_type,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        }
        for media_type, data in images
    ]
    payload = {
        "v": 1,
        "kind": kind,
        "provider_id": config.provider_id,
        "adapter": config.adapter,
        "base_url": config.base_url,
        "credential_scope": credential_scope,
        "model": model,
        "max_tokens": max_tokens,
        "effort": effort,
        "system": system,
        "user": user,
        "output_schema": output_schema,
        "images": image_fingerprints,
    }
    return hashlib.sha256(compact_json(payload).encode("utf-8")).hexdigest()


class ExactResponseCache:
    """Thread-safe bounded LRU cache with privacy-safe aggregate metrics."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._entries: OrderedDict[str, str] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._writes = 0
        self._evictions = 0

    def get(self, key: str) -> str | None:
        capacity = _capacity()
        with self._lock:
            if capacity <= 0:
                self._misses += 1
                return None
            value = self._entries.get(key)
            if value is None:
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            return value

    def put(self, key: str, value: str) -> None:
        capacity = _capacity()
        if capacity <= 0:
            return
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            self._writes += 1
            while len(self._entries) > capacity:
                self._entries.popitem(last=False)
                self._evictions += 1

    def clear(self, *, reset_metrics: bool = False) -> None:
        with self._lock:
            self._entries.clear()
            if reset_metrics:
                self._hits = 0
                self._misses = 0
                self._writes = 0
                self._evictions = 0

    def reset(self) -> None:
        self.clear(reset_metrics=True)

    def snapshot(self) -> dict[str, int | float | bool]:
        with self._lock:
            requests = self._hits + self._misses
            capacity = _capacity()
            return {
                "enabled": capacity > 0,
                "memory_only": True,
                "size": len(self._entries),
                "max_entries": capacity,
                "requests": requests,
                "cache_hits": self._hits,
                "api_calls_saved": self._hits,
                "misses": self._misses,
                "writes": self._writes,
                "evictions": self._evictions,
                "reuse_rate": round(self._hits / requests, 3) if requests else 0.0,
            }


response_cache = ExactResponseCache()
