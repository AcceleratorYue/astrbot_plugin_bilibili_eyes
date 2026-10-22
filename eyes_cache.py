"""笔记缓存（磁盘 digest）与会话材料缓存（内存，供追问/截图）。"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class NoteCache:
    def __init__(
        self,
        directory: Path,
        ttl_hours: int = 168,
        max_entries: int = 500,
        version: str = "",
    ):
        self.directory = Path(directory)
        self.ttl_seconds = max(1, int(ttl_hours)) * 3600
        self.max_entries = max(1, int(max_entries))
        self.version = str(version or "")
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, bvid: str, page: int) -> Path:
        suffix = f"_v{self.version}" if self.version else ""
        return self.directory / f"{bvid}_p{int(page)}{suffix}.json"

    def get(self, bvid: str, page: int) -> str | None:
        path = self._path(bvid, page)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
        created = float(payload.get("created") or 0)
        if time.time() - created > self.ttl_seconds:
            try:
                path.unlink()
            except Exception:
                pass
            return None
        digest = payload.get("digest")
        return str(digest) if digest else None

    def set(self, bvid: str, page: int, digest: str, meta: dict | None = None) -> None:
        if not digest:
            return
        payload = {
            "bvid": bvid,
            "page": int(page),
            "digest": digest,
            "created": time.time(),
            "meta": meta or {},
        }
        path = self._path(bvid, page)
        try:
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            return
        self._prune()

    def _prune(self) -> None:
        files = sorted(
            self.directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        now = time.time()
        for path in files:
            try:
                if now - path.stat().st_mtime > self.ttl_seconds:
                    path.unlink()
            except Exception:
                pass
        for path in files[self.max_entries :]:
            try:
                path.unlink()
            except Exception:
                pass


class MaterialStore:
    """会话材料缓存：只保留最近看过的视频材料，30 分钟过期，不落盘。"""

    def __init__(self, ttl_seconds: int = 1800, max_entries: int = 20):
        self.ttl_seconds = max(60, int(ttl_seconds))
        self.max_entries = max(1, int(max_entries))
        self._items: dict[str, tuple[float, Any, str]] = {}

    def put(self, umo: str, material: Any, digest: str = "") -> None:
        self._items[str(umo)] = (time.monotonic(), material, str(digest or ""))
        self._prune()

    def get(self, umo: str) -> tuple[Any, str] | None:
        self._prune()
        item = self._items.get(str(umo))
        if not item:
            return None
        created, material, digest = item
        if time.monotonic() - created > self.ttl_seconds:
            self._items.pop(str(umo), None)
            return None
        return material, digest

    def drop(self, umo: str) -> None:
        self._items.pop(str(umo), None)

    def _prune(self) -> None:
        now = time.monotonic()
        expired = [
            key
            for key, (created, _material, _digest) in self._items.items()
            if now - created > self.ttl_seconds
        ]
        for key in expired:
            self._items.pop(key, None)
        if len(self._items) <= self.max_entries:
            return
        ordered = sorted(self._items.items(), key=lambda item: item[1][0])
        for key, _value in ordered[: len(self._items) - self.max_entries]:
            self._items.pop(key, None)
