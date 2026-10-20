"""A dead-simple on-disk cache for API responses.

Why bother? Both APIs have rate limits, and while you are learning you will
run the same search many times. Each response is stored as one JSON file named
after a hash of the request, and is reused until it is older than the TTL
(24 hours by default).

Use `--no-cache` to ignore stored copies, or `--refresh` to overwrite them.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


class Cache:
    def __init__(self, directory: Path, ttl_hours: float = 24.0, enabled: bool = True):
        self.directory = Path(directory)
        self.ttl_seconds = max(0.0, ttl_hours) * 3600.0
        self.enabled = enabled
        self.hits = 0
        self.misses = 0
        if self.enabled:
            self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, namespace: str, key: dict[str, Any]) -> Path:
        # Sorted keys so the same request always produces the same filename.
        blob = json.dumps(key, sort_keys=True, default=str).encode("utf-8")
        digest = hashlib.sha256(blob).hexdigest()[:20]
        safe_ns = "".join(c if c.isalnum() or c in "-_" else "_" for c in namespace)
        return self.directory / f"{safe_ns}-{digest}.json"

    def get(
        self, namespace: str, key: dict[str, Any], ttl_hours: float | None = None
    ) -> Any | None:
        """Return the cached value, or None if absent/expired/unreadable.

        `ttl_hours` overrides the default lifetime for this one lookup, which
        suits data that barely changes -- Etsy's category tree, say, is worth
        keeping for weeks rather than re-downloading daily.
        """
        if not self.enabled:
            return None
        path = self._path(namespace, key)
        if not path.is_file():
            self.misses += 1
            return None
        ttl = self.ttl_seconds if ttl_hours is None else max(0.0, ttl_hours) * 3600.0
        if ttl and (time.time() - path.stat().st_mtime) > ttl:
            self.misses += 1
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # A corrupt cache file should never crash the tool.
            self.misses += 1
            return None
        self.hits += 1
        return payload.get("value")

    def set(self, namespace: str, key: dict[str, Any], value: Any) -> None:
        if not self.enabled:
            return
        path = self._path(namespace, key)
        payload = {"cached_at": time.time(), "key": key, "value": value}
        try:
            path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        except OSError:
            pass  # Caching is a nicety; never let it break a search.

    def clear(self) -> int:
        """Delete every cached file. Returns how many were removed."""
        if not self.directory.is_dir():
            return 0
        removed = 0
        for path in self.directory.glob("*.json"):
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed
