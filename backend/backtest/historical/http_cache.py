from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backtest.io import load_json, write_json


USER_AGENT = "LineupLab historical validation/1.0 (+offline-cache-required)"


class HttpCacheError(RuntimeError):
    pass


@dataclass(frozen=True)
class CachedHttpResponse:
    url: str
    body: bytes
    sha256: str
    fetched_at: datetime
    cache_key: str
    from_cache: bool
    headers: dict[str, str]

    @property
    def byte_count(self) -> int:
        return len(self.body)

    def json(self) -> object:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HttpCacheError(f"cached response is not valid UTF-8 JSON: {self.url}") from exc


Transport = Callable[[str, float], tuple[bytes, Mapping[str, str]]]
Clock = Callable[[], datetime]
Sleep = Callable[[float], None]


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include a timezone offset")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise HttpCacheError("cache metadata fetched_at is not timezone-aware")
    return parsed


def _default_transport(url: str, timeout: float) -> tuple[bytes, Mapping[str, str]]:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        return response.read(), dict(response.headers.items())


class ImmutableHttpCache:
    """Content-addressed HTTP cache with deterministic offline replay.

    A successful network response is written once. Existing cache entries are never
    silently replaced. If the same URL later returns different bytes, the caller must
    use a different cache directory or explicitly remove the old entry after auditing.
    """

    def __init__(
        self,
        root: Path,
        *,
        transport: Transport | None = None,
        clock: Clock = _utc_now,
        sleep: Sleep = time.sleep,
    ):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.transport = transport or _default_transport
        self.clock = clock
        self.sleep = sleep

    @staticmethod
    def cache_key(url: str) -> str:
        return hashlib.sha256(url.encode("utf-8")).hexdigest()

    def paths(self, url: str) -> tuple[Path, Path]:
        key = self.cache_key(url)
        return self.root / f"{key}.body", self.root / f"{key}.meta.json"

    def fetch_json(
        self,
        url: str,
        *,
        offline: bool = False,
        retries: int = 3,
        timeout: float = 20.0,
    ) -> CachedHttpResponse:
        if retries < 1:
            raise ValueError("retries must be at least 1")
        body_path, meta_path = self.paths(url)
        if body_path.exists() or meta_path.exists():
            return self._load(url, body_path, meta_path)
        if offline:
            raise HttpCacheError(
                "offline cache miss for "
                f"{url}; expected {body_path.name} and {meta_path.name}"
            )

        failures: list[str] = []
        for attempt in range(1, retries + 1):
            try:
                body, headers = self.transport(url, timeout)
                json.loads(body.decode("utf-8"))
            except (HTTPError, URLError, OSError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                failures.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
                if attempt < retries:
                    self.sleep(float(attempt))
                continue

            fetched_at = self.clock()
            if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
                raise HttpCacheError("cache clock must return a timezone-aware datetime")
            digest = hashlib.sha256(body).hexdigest()
            metadata = {
                "schema_version": "1.0",
                "url": url,
                "cache_key": self.cache_key(url),
                "fetched_at": _iso(fetched_at),
                "byte_count": len(body),
                "sha256": digest,
                "headers": {str(key): str(value) for key, value in sorted(headers.items())},
            }
            body_path.write_bytes(body)
            write_json(meta_path, metadata)
            return CachedHttpResponse(
                url=url,
                body=body,
                sha256=digest,
                fetched_at=fetched_at,
                cache_key=metadata["cache_key"],
                from_cache=False,
                headers=metadata["headers"],
            )

        raise HttpCacheError(
            f"failed to fetch {url} after {retries} attempts: " + " | ".join(failures)
        )

    def _load(self, url: str, body_path: Path, meta_path: Path) -> CachedHttpResponse:
        if not body_path.exists() or not meta_path.exists():
            raise HttpCacheError(
                f"incomplete cache entry for {url}: body/meta must both exist"
            )
        metadata = load_json(meta_path)
        body = body_path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        expected = str(metadata.get("sha256", ""))
        if metadata.get("url") != url:
            raise HttpCacheError(f"cache URL mismatch for {url}")
        if metadata.get("cache_key") != self.cache_key(url):
            raise HttpCacheError(f"cache key mismatch for {url}")
        if int(metadata.get("byte_count", -1)) != len(body):
            raise HttpCacheError(f"cache byte count mismatch for {url}")
        if expected != digest:
            raise HttpCacheError(
                f"cache SHA-256 mismatch for {url}: expected {expected}, got {digest}"
            )
        try:
            json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HttpCacheError(f"cache body is not valid JSON for {url}") from exc
        return CachedHttpResponse(
            url=url,
            body=body,
            sha256=digest,
            fetched_at=_parse_datetime(str(metadata["fetched_at"])),
            cache_key=str(metadata["cache_key"]),
            from_cache=True,
            headers={str(key): str(value) for key, value in metadata.get("headers", {}).items()},
        )
