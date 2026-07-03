from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol


BACKEND_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CACHE_DIR = Path(os.getenv("CACHE_DIR", str(BACKEND_DIR / "cache")))


class CacheStore(Protocol):
    def exists(self, key: str) -> bool: ...

    def read_json(self, key: str, default: Any = None) -> Any: ...

    def write_json(self, key: str, data: Any) -> None: ...


class LocalJsonCacheStore:
    def __init__(self, root: Path = DEFAULT_CACHE_DIR) -> None:
        self.root = root

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def read_json(self, key: str, default: Any = None) -> Any:
        path = self._path(key)
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text())
        except json.JSONDecodeError:
            return default

    def write_json(self, key: str, data: Any) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        tmp_path.write_text(json.dumps(data, indent=2, sort_keys=True, default=str))
        os.replace(tmp_path, path)

    def _path(self, key: str) -> Path:
        normalized = key.strip().lstrip("/")
        if not normalized.endswith(".json"):
            normalized = f"{normalized}.json"
        path = (self.root / normalized).resolve()
        root = self.root.resolve()
        if root != path and root not in path.parents:
            raise ValueError(f"cache key escapes cache root: {key}")
        return path


cache_store: CacheStore = LocalJsonCacheStore()
