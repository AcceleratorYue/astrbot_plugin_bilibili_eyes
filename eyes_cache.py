"""笔记缓存（只缓存 digest，不缓存原始材料）。"""

from __future__ import annotations

import json
import time
from pathlib import Path


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
